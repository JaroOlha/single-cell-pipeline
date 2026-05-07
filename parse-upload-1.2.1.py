import sys
import traceback

# Check minimum required python version is available
if sys.version_info < (3, 7):

    print("This script requires Python 3.7 or later. You are using Python {}.{}.{}. Upgrade your python version to 3.7 or higher and try again.".format(
            sys.version_info.major, sys.version_info.minor, sys.version_info.micro
        )
    )
    exit(0)

import argparse
import glob
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait
from threading import Event, Lock
import datetime

SCRIPT_VERSION = "1.2.1"

MAX_RETRIES = 8  # Max number of retries to upload each PART_SIZE part
MIN_THREADS_COUNT = 20
MAX_THREADS_COUNT = 60

# S3 multipart upload limits
PART_SIZE_MIN = 5 * 1024 * 1024
PART_COUNT_MAX = 10000

# Groups of signed urls that are refreshed and expire together
SIGNED_URLS_BATCH_SIZE = 500

TIMEOUT_PUT_PART_SECONDS = 3600

# To run other than in production, run the following environment command: export PARSE_API_URL=<api-base-url>

# Staging url
# default_prod_api_url = "https://api-default.staging.trailmaker.parsebiosciences.com/v2"


# local url
# default_prod_api_url = "http://localhost:3000/v2"
# Production url
default_prod_api_url = "https://api.app.trailmaker.parsebiosciences.com/v2"

base_url = os.environ.get("PARSE_API_URL") or default_prod_api_url

RESUME_PARAMS_PATH = "resume_params.txt"
# Line-by-line format for resume_params.txt:
# 1: analysis_id
# 2: upload_params (JSON) { fileId: string, uploadId: string, bucket: string, key: string }
# 3: current_file_created ("True"/"False")
# 4: file_list (JSON array of {"path","type"} objects)
# 5: current_file_index (int)
# 6: free_part_ranges (JSON produced by PartsProvider.get_pending_parts_for_save_str(), check that for format)
# 7: SCRIPT_VERSION
# Example:
# 15a03fa2-3d06-48ee-8e42-8f33a10b4cda
# {"fileId":"...","uploadId":"...","bucket":"...","key":"..."}
# True
# [{"path":"/path/a.fastq.gz","type":"immuneFastq"}]
# 0
# [[0,10],[15,20]]
# 1.2.1
ETAGS_PATH = "part_etags.txt"

CLEAN_ERROR_PATH = "parse_upload_clean_error.log"
REQUEST_ERROR_PATH = "parse_upload_request_error.log"

CURSOR_UP_ONE = "\x1b[1A"
ERASE_CURRENT_LINE = "\x1b[2K"
ERASE_UPPER_LINE = CURSOR_UP_ONE + ERASE_CURRENT_LINE


MESSAGE_ERROR_FASTQS_SOLUTION = "You can delete the fastq files that didn't finish through the browser and upload them again from scratch"

def wipe_file(file_path):
    with open(file_path, "w"):
        pass

def cleanup_old_error_logs():
    try:
        os.remove(CLEAN_ERROR_PATH)
    except: pass

    try:
        os.remove(REQUEST_ERROR_PATH)
    except: pass

def get_resume_params_from_file(version_check=False):
    if not os.path.exists(RESUME_PARAMS_PATH):
        raise Exception("No resume parameters file {} found, try beginning a new upload".format(RESUME_PARAMS_PATH))
    with open(RESUME_PARAMS_PATH, "r") as file:
        lines = file.read().splitlines()
        if (version_check):
            if (len(lines) < 7 or lines[6] != SCRIPT_VERSION):
                print("""[WARNING] The upload you are about to resume seems to have been begun with an older script than the one you are using now.
    This might lead to unexpected errors. If you encounter any issues, consider beginning the upload again from scratch.""")
                input("If you want to continue with the current version, press ENTER. Otherwise, press CTRL+C to cancel the upload\n")

            if not (len(lines) in [6,7]):
                raise Exception(
                    "Resume file {} corrupted. {}".format(RESUME_PARAMS_PATH, MESSAGE_ERROR_FASTQS_SOLUTION)
                )

        analysis_id = lines[0]
        upload_params = json.loads(lines[1])
        current_file_created = lines[2] == "True"
        file_list = []
        # resume file might be in the old format
        # todo remove after some time when we are sure no one uses the old format
        try:
            file_list = json.loads(lines[3])
        except json.JSONDecodeError:
            files = lines[3].split(",")
            for file in files:
                file_list.append({"path": file, "type": "wtFastq"})

        current_file_index = int(lines[4])
        free_part_ranges = json.loads(lines[5])

        return (
            analysis_id,
            upload_params,
            file_list,
            current_file_index,
            free_part_ranges,
            current_file_created
        )


def with_retry(func, try_number=0):
    try:
        return func()
    except Exception as e:
        if try_number >= MAX_RETRIES:
            raise e

        wait_seconds = 2**try_number

        time.sleep(wait_seconds)

        return with_retry(func, try_number + 1)

def parsed_expire_time(expire_time_str):
    iso_str = expire_time_str.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(iso_str).timestamp()

class HTTPResponse:
    def __init__(self, response, response_data=None):
        self._response = response
        self._response_data = response_data
        self._is_error = isinstance(self._response, Exception)
    def json(self):
        if self._response_data == None:
            raise Exception("Internal error, please try again.")

        return json.loads(self._response_data)

    @property
    def text(self):
        if (hasattr(self._response, 'reason')):
            return self._response.reason
        return str(self._response)

    @property
    def headers(self):
        return dict(self._response.getheaders())

    @property
    def status_code(self):
        if self._is_error:
            if isinstance(self._response, urllib.error.HTTPError):
                return self._response.code

            return None

        return self._response.status


def http_put_part(signed_url, data):
    headers = {"Content-Type": "application/octet-stream"}
    request = urllib.request.Request(signed_url, data=data, headers=headers, method="PUT")

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_PUT_PART_SECONDS) as response:
            return HTTPResponse(response)

    except Exception as e:
        store_error(e, REQUEST_ERROR_PATH)
        return HTTPResponse(e)

def http_get(url, headers):
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")

        with urllib.request.urlopen(request) as response:
            return HTTPResponse(response, response.read())

    except Exception as e:
        store_error(e, REQUEST_ERROR_PATH)
        return HTTPResponse(e)

def http_post(url, headers, json_data={}):
    headers["Content-Type"] = "application/json"
    data = json.dumps(json_data).encode("utf-8")

    try:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request) as response:
            return HTTPResponse(response, response.read())
    except urllib.error.HTTPError as e:
        error_body = e.read()
        store_error(e, REQUEST_ERROR_PATH)
        return HTTPResponse(e, error_body)
    except Exception as e:
        store_error(e, REQUEST_ERROR_PATH)
        return HTTPResponse(e)

# Manages
# - the parameters required for upload,
# - the upload progress (both parts and files)
# - persisting the current upload so that it is resumable
class UploadTracker:
    def __init__(
        self,
        analysis_id,
        file_list,
        current_file_index,
        free_part_ranges,
        upload_params,
        current_file_created,
        api_token,
        threads_count
    ):
        self.analysis_id = analysis_id
        self.file_list = file_list
        self.current_file_index = current_file_index
        self.current_file_created = current_file_created
        self.upload_params = upload_params
        self.api_token = api_token
        self.threads_count = threads_count

        file_path = self.file_list[self.current_file_index]["path"]
        self.parts_provider = PartsProvider(file_path, free_part_ranges)

        self.files_lock = Lock()

    @classmethod
    def fromScratch(cls, analysis_id, file_dict, api_token, threads_count):
        file_list = []
        for fastq_type, paths in file_dict.items():
            for path in paths:
                file_list.append({"path": path, "type": fastq_type})

        # Starting from scratch, so wipe files
        cls.wipe_current_upload()

        return cls(
            analysis_id,
            file_list,
            0,
            None,
            None,
            False,
            api_token,
            threads_count
        )


    @classmethod
    def fromResumeFile(cls, api_token, threads_count):
        (
            analysis_id,
            upload_params,
            file_list,
            current_file_index,
            free_part_ranges,
            current_file_created,
        ) = get_resume_params_from_file(version_check=True)

        return cls(
            analysis_id,
            file_list,
            current_file_index,
            free_part_ranges,
            upload_params,
            current_file_created,
            api_token,
            threads_count
        )

    @classmethod
    def delete_temp_files(cls):
        os.remove(ETAGS_PATH)
        os.remove(RESUME_PARAMS_PATH)

    # Keeps the files but leaves them empty
    @classmethod
    def wipe_current_upload(cls):
        wipe_file(ETAGS_PATH)
        wipe_file(RESUME_PARAMS_PATH)

    def save_progress(self):
        with open(RESUME_PARAMS_PATH, "w") as file:
            file.write(
                "\n".join(
                    [
                        "{}".format(self.analysis_id),
                        json.dumps(self.upload_params),
                        str(self.current_file_created),
                        json.dumps(self.file_list),
                        "{}".format(self.current_file_index),
                        self.parts_provider.get_pending_parts_for_save_str(),
                        SCRIPT_VERSION,
                    ]
                )
            )

    def get_upload_params(self):
        if not self.current_file_created:
            self.upload_params = begin_multipart_upload(
                self.analysis_id,
                self.file_list[self.current_file_index],
                self.api_token,
            )
            self.current_file_created = True
            self.save_progress()

        return self.upload_params

    def get_global_progress(self):
        current_file_info = self.file_list[self.current_file_index]

        return (
            self.analysis_id,
            current_file_info["path"],
            self.parts_provider,
            current_file_info["type"]
        )

    def get_parts_etags(self):
        if not os.path.exists(ETAGS_PATH):
            raise Exception("File {} doesn't exist".format(ETAGS_PATH))

        with open(ETAGS_PATH, "r") as file:
            lines = file.read().splitlines()
            return [
                {
                    "PartNumber": int(line.split(",")[0]),
                    "ETag": line.split(",")[1].strip(""),
                }
                for line in lines
            ]

    def is_finished(self):
        return self.current_file_index >= len(self.file_list)

    def file_uploaded(self):
        self.current_file_index += 1
        self.current_file_created = False

        if self.is_finished():
            return

        file_path = self.file_list[self.current_file_index]["path"]
        self.parts_provider = PartsProvider(file_path, None)

        self.save_progress()

        # Wipe PART_ETAGS_PATH file, upload was completed
        with open(ETAGS_PATH, "w"):
            pass

    def part_uploaded(self, part_number, etag):
        with self.files_lock:
            with open(ETAGS_PATH, "a") as file:
                # write etag without the double commas
                file.write("{},{}".format(part_number, etag))
                file.write("\n")

            self.save_progress()


class ProgressDisplayer:
    def __init__(self, total, progress, file_path):
        super().__init__()

        self.total = total
        self.progress = progress
        self.file_path = file_path
        self.increase_lock = Lock()

    def begin(self):
        self._display_progress()

    def increment(self):
        with self.increase_lock:
            self.progress += 1
            self._display_progress()

    def show_completing(self):
        sys.stdout.write(
            "\r\033[KCompleting upload, this could take a few minutes with large files"
        )

    def finish(self):
        sys.stdout.write(ERASE_CURRENT_LINE)
        sys.stdout.write(ERASE_UPPER_LINE)
        sys.stdout.write("\rUploaded file {}\n".format(self.file_path))
        print()  # Move to the next line

    def _display_progress(self):
        percentage = (self.progress / self.total) * 100
        progress_bar = "#" * int(percentage // 2)

        sys.stdout.write(ERASE_UPPER_LINE)

        sys.stdout.write("\rUploading file {}\n".format(self.file_path))
        sys.stdout.write("\rProgress: [{:<50}] {:.2f}%".format(progress_bar, percentage))

class SignedUrlsProvider:
    def __init__(self, analysis_id, upload_id, key, api_token, number_of_parts):
        self.analysis_id = analysis_id
        self.upload_id = upload_id
        self.key = key
        self.api_token = api_token


        self.parts_count = number_of_parts
        batches_count = math.ceil(number_of_parts / SIGNED_URLS_BATCH_SIZE)

        self.signed_urls_by_part_index = [None] * self.parts_count
        self.signed_urls_expire_time_by_batch = [None] * batches_count

        self.signed_urls_lock = Lock()

        # Set of batch indexes currently being refreshed
        self.signed_urls_refreshing = set()

        # Dict of batch_index -> Event, filled lazily when a refresh for a batch is first called
        self.signed_urls_refresh_events = {}

    def get_signed_url_for_part(self, part_index):
        signed_url = self.signed_urls_by_part_index[part_index]

        if signed_url is None or self._is_signed_urls_expired(part_index):
            self._atomic_refresh_signed_urls(part_index)

            signed_url = self.signed_urls_by_part_index[part_index]

        if (signed_url is None):
            raise Exception("Failed to obtain signed url for part {}, check your internet connection and try resuming the upload".format(part_index + 1))

        return signed_url

    def _is_signed_urls_expired(self, part_index):
        batch_index = part_index // SIGNED_URLS_BATCH_SIZE

        expire_time = self.signed_urls_expire_time_by_batch[batch_index]

        return expire_time is None or time.time() >= expire_time

    def _fetch_batch_signed_urls(self, batch_parts_count, parts_offset_index):
        # + 1 to partsOffset because we are using 1-indexed part numbers in the backend (s3 uses 1-indexing for parts)
        response = http_post(
            "{}/analysis/{}/cliUpload/{}/batchSignedUrls".format(base_url, self.analysis_id, self.upload_id),
            {"X-Api-Token": "Bearer {}".format(self.api_token)},
            json_data={"key": self.key, "partsCount": batch_parts_count, "partsOffset": parts_offset_index},
        )

        if response.status_code != 200:
            raise Exception(
                "Failed to begin upload of part of the file to our servers, check your internet connection and try resuming the upload"
            )

        signed_urls = response.json().get("signedUrls")
        expire_time_str = response.json().get("expireTime")

        if (batch_parts_count != len(signed_urls)):
            raise Exception("Received an invalid amount of signed urls from the server, check your internet connection and try resuming the upload and let us know about this problem")

        expire_time = parsed_expire_time(expire_time_str)

        return signed_urls, expire_time

    def _refresh_signed_urls(self, batch_index):
        parts_offset = batch_index * SIGNED_URLS_BATCH_SIZE

        batch_size = min(SIGNED_URLS_BATCH_SIZE, self.parts_count - parts_offset)

        batch_signed_urls, batch_signed_urls_expire_time = self._fetch_batch_signed_urls(batch_size, parts_offset)

        if (batch_size != len(batch_signed_urls)):
            raise Exception("Received an invalid amount of signed urls from the server, check your internet connection and try resuming the upload and let us know about this problem")

        # Replace signed urls in the corresponding batch
        self.signed_urls_by_part_index[parts_offset: parts_offset + batch_size] = batch_signed_urls

        # Update signed url expire time
        self.signed_urls_expire_time_by_batch[batch_index] = batch_signed_urls_expire_time

    def _atomic_refresh_signed_urls(self, part_index):
        batch_index = part_index // SIGNED_URLS_BATCH_SIZE

        event = None

        with self.signed_urls_lock:
            # Lazy creation
            if batch_index not in self.signed_urls_refresh_events:
                self.signed_urls_refresh_events[batch_index] = Event()
                self.signed_urls_refresh_events[batch_index].set()

            # If this batch is already being refreshed, wait for it to finish
            if batch_index in self.signed_urls_refreshing:
                event = self.signed_urls_refresh_events[batch_index]

            else:
                self.signed_urls_refreshing.add(batch_index)
                self.signed_urls_refresh_events[batch_index].clear()

        if event is not None:
            event.wait()
            return

        try:
            self._refresh_signed_urls(batch_index)
        except Exception as e:
            with self.signed_urls_lock:
                self.signed_urls_refreshing.remove(batch_index)
                self.signed_urls_refresh_events[batch_index].set()
            raise e

        with self.signed_urls_lock:
            self.signed_urls_refreshing.remove(batch_index)
            self.signed_urls_refresh_events[batch_index].set()

class PartsProvider:
    def __init__(self, file_path, free_part_ranges):
        file_size = os.path.getsize(file_path)

        # Can't have more than 10000 parts
        minimum_part_size = math.ceil(file_size / PART_COUNT_MAX)
        # Can't use part sizes smaller than 5mb
        self.part_size = max(minimum_part_size, PART_SIZE_MIN)
        self.number_of_parts = math.ceil(file_size / self.part_size)

        self.file_path = file_path

        # Ranges are used as [start, end), begin with one range with all the parts
        if (free_part_ranges is not None):
            # Saved ranges can have duplicate parts to make the saving process faster
            # so on load we need to deduplicate and merge them to avoid uploading parts more than once
            self.free_part_ranges = self._deduplicated_and_merged_ranges(free_part_ranges)

            if (len(self.free_part_ranges) != 0 and self.free_part_ranges[-1][1] > self.number_of_parts):
                raise Exception("Resume file {} corrupted, it contains invalid part ranges. {}".format(RESUME_PARAMS_PATH, MESSAGE_ERROR_FASTQS_SOLUTION))
        else:
            self.free_part_ranges = [[0, self.number_of_parts]]

        self.uploading_parts = set()
        self.parts_lock = Lock()

    def get_next_part(self):
        with self.parts_lock:
            # Case we are done uploading
            if (len(self.free_part_ranges) == 0):
                return None, None

            part_index = self._get_lowest_free_part()

        with open(self.file_path, "rb") as file:
            file.seek(part_index * self.part_size)
            part = file.read(self.part_size)

        return part, part_index

    # Sorts ranges and merges them when possible to avoid parts being stored more than once
    def _deduplicated_and_merged_ranges(self, ranges_with_duplicates):
        if (len(ranges_with_duplicates) == 0):
            return []

        ranges_with_duplicates.sort(key=lambda part_range: part_range[0])

        merged_ranges = [ranges_with_duplicates[0]]
        for start, end in ranges_with_duplicates[1:]:
            [previous_start, previous_end] = merged_ranges[-1]

            if previous_end >= start:
                merged_ranges[-1] = [previous_start, max(previous_end, end)]
            else:
                merged_ranges.append([start, end])

        return merged_ranges

    # Returns everything that isn't uploaded yet, so a combination of free parts and currently uploading parts
    # Can have intersecting ranges (this is handled when it actually matters: on load)
    def get_pending_parts_for_save_str(self):
        with self.parts_lock:
            free_part_ranges_snap = self.free_part_ranges.copy()
            uploading_parts_snap = self.uploading_parts.copy()

        uploading_parts_ranges = [[pending_part_index, pending_part_index + 1] for pending_part_index in uploading_parts_snap]

        return json.dumps(uploading_parts_ranges + free_part_ranges_snap)

    def get_progress(self):
        return self.number_of_parts - sum([end - start for start, end in self.free_part_ranges])

    # TODO current version, maybe make it prompt the upload tracker to save progress from in here?
    # Or just return the new shape and make it be passed to the upload tracker, but that's kind of ugly
    def part_uploaded(self, part_index):
        with self.parts_lock:
            self.uploading_parts.remove(part_index)

    def _get_lowest_free_part(self):
        part_index = self.free_part_ranges[0][0]

        self.uploading_parts.add(part_index)

        self.free_part_ranges[0][0] += 1

        if (self.free_part_ranges[0][0] == self.free_part_ranges[0][1]):
            self.free_part_ranges.pop(0)

        return part_index


# Manages the upload of a single file
class FileUploader:
    def __init__(self, upload_tracker):
        (analysis_id, file_path, parts_provider, fastq_type) = (
            upload_tracker.get_global_progress()
        )

        self.analysis_id = analysis_id
        self.api_token = upload_tracker.api_token
        self.threads_count = upload_tracker.threads_count
        self.upload_tracker = upload_tracker

        self.fastq_type = fastq_type
        self.file_path = file_path

        self.parts_provider = parts_provider

        self.progress_displayer = ProgressDisplayer(
            self.parts_provider.number_of_parts, self.parts_provider.get_progress(), file_path
        )

        # These will be obtained from begin_multipart_upload()
        self.upload_id = None
        self.key = None
        self.file_id = None
        self.signed_urls_provider = None

    def complete_multipart_upload(self, parts):
        self.progress_displayer.show_completing()

        # AWS expects parts to be sent in order:
        # https://docs.aws.amazon.com/AmazonS3/latest/API/API_CompleteMultipartUpload.html?utm_source=openai#:~:text=Error%20Code%3A%20InvalidPartOrder,Code%3A%20400%20Bad%20Request
        sorted_parts = sorted(parts, key=lambda part: part["PartNumber"])

        response = http_post(
            "{}/analysis/{}/cliUpload/CompleteMultipartUpload".format(base_url, self.analysis_id),
            {"X-Api-Token": "Bearer {}".format(self.api_token)},
            json_data={
                "key": self.key,
                "uploadId": self.upload_id,
                "parts": sorted_parts,
                "fileId": self.file_id,
            },
        )

        if response.status_code != 200:
            raise Exception(
                "Failed to complete upload for file {}, check your internet connection and try resuming the upload".format(self.file_path)
            )

    def upload_part(self, part, part_index):
        signed_url = self.signed_urls_provider.get_signed_url_for_part(part_index)

        response = http_put_part(signed_url, part)

        if response.status_code != 200:
            raise Exception("""Upload of part of the file failed, check your internet connection and try resuming the upload, \n\nError details: {}""".format(response.text))

        # With localstack the ETag is returned lowercase for some reason
        etag = response.headers.get("ETag", response.headers.get("etag"))
        if etag == None:
            raise Exception("Unexpected response from the server")

        return etag

    def upload_file_parts(self, abort_event):
        try:
            while True:
                if abort_event.is_set():
                    return

                part, part_index = self.parts_provider.get_next_part()

                if part_index == None:
                    return

                etag = with_retry(lambda: self.upload_part(part, part_index))

                self.parts_provider.part_uploaded(part_index)
                self.upload_tracker.part_uploaded(part_index + 1, etag)

                self.progress_displayer.increment()

        except Exception as e:
            # If an exception occurs, set the abort event to that the other threads stop too
            abort_event.set()
            raise e


    def upload_file(self):
        self.progress_displayer.begin()

        upload_params = self.upload_tracker.get_upload_params()

        self.upload_id = upload_params["uploadId"]
        self.key = upload_params["key"]
        self.file_id = upload_params["fileId"]
        self.signed_urls_provider = SignedUrlsProvider(
            self.analysis_id,
            self.upload_id,
            self.key,
            self.api_token,
            self.parts_provider.number_of_parts
        )

        abort_event = Event()

        with ThreadPoolExecutor(self.threads_count) as executor:
            futures = []

            for _ in range(self.threads_count):
                futures.append(
                    executor.submit(
                        self.upload_file_parts,
                        abort_event,
                    )
                )

            # not_done will always be empty because wait doesn't have a timeout.
            done, not_done = wait(futures)

            for future in done:
                future.result()

        etags = self.upload_tracker.get_parts_etags()
        with_retry(lambda: self.complete_multipart_upload(etags))

        self.upload_tracker.file_uploaded()
        self.progress_displayer.finish()


def upload_all_files(upload_tracker):
    while not upload_tracker.is_finished():
        uploader = FileUploader(upload_tracker)
        uploader.upload_file()

    # Finished upload, so wipe the resume files
    UploadTracker.delete_temp_files()
    print()
    print("Upload completed successfully!")


def begin_multipart_upload(analysis_id, file, api_token):
    file_path = file["path"]
    fastq_type = file["type"]
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    url = "{}/analysis/{}/cliUpload/begin".format(base_url, analysis_id)

    response = http_post(
        url,
        {"X-Api-Token": "Bearer {}".format(api_token)},
        json_data={"name": file_name, "size": file_size, "type": fastq_type},
    )

    if response.status_code != 200:
        if response.status_code == 400:
            error = response.json()
            raise Exception(error["message"])
        if response.status_code == 401:
            raise Exception(
                "Not authorized to upload files to this run, please verify your --run_id and --token"
            )

        if response.status_code == 409:
            raise Exception(
                "File {} already exists in the run. Please remove the existing one from the platform using the browser before uploading this file".format(file_path)
            )
        if response.status_code == 404:
            raise Exception("Error 404: Not found")

        raise Exception("Failed to begin upload for file {}, please check your files and internet connection and try again by resuming the upload\nIf the problem persists try starting the upload again from the beginning. \n\n {}".format(file_path, response.text))

    upload_params = response.json()

    return upload_params


# Show a warning if there is a previous upload that can be resumed
def show_resume_option():
    if os.path.exists(RESUME_PARAMS_PATH):
        (
            analysis_id,
            upload_params,
            file_list,
            current_file_index,
            free_part_ranges,
            current_file_created,
        ) = None, None, None, None, None, None

        try:
            (
                analysis_id,
                upload_params,
                file_list,
                current_file_index,
                free_part_ranges,
                current_file_created,
            ) = get_resume_params_from_file()

        # Ignore file if it is corrupted
        except Exception:
            return False

        print(
            "It seems an interrupted upload for analysis id: {} can be resumed, or will be lost if a new upload is started".format(analysis_id)
        )
        print()
        print("It included the following files:")
        for file in file_list:
            print(file['path'])
        print("")

        # Prompt the user to confirm that they want to overwrite the previous upload that can be resumed

        the_input = input(
            "Write 'resume' and press ENTER to resume this analysis instead of starting a new one, otherwise just press ENTER to continue with the new upload: "
        )
        if the_input == "resume":
            return True

    return False


def show_files_to_upload_warning(file_list):
    if len(file_list) == 0:
        raise Exception(
            "No valid files found to upload, please check the --file parameter values or use --help for more information"
        )

    print("New upload: the following files will be uploaded:")
    for file in file_list:
        print(file['path'])
    print("")
    print(
        'If these are the correct files, press ENTER. Otherwise write "no" and press ENTER to cancel the upload.'
    )
    the_input = input()
    if the_input == "no":
        raise Exception("Upload cancelled")

regex = r'_R([12])|_([12])\.(fastq|fq)\.gz$'

def check_names_are_valid(files):
    for file in files:
        file_name = file.split("/")[-1]

        if not (file_name.endswith(".fastq.gz") or file_name.endswith(".fq.gz")):
            raise Exception(
                "File {} does not end with .fastq.gz or fq.gz, only gzip compressed fastq files are supported".format(file_name)
            )

        if not re.search(regex, file_name):
            raise Exception(
                "File {} must either: contain _R1 or _R2 in its name, or end with _1 or _2, please check the file name to ensure it is a valid fastq pair".format(file_name)
            )

        if file_name.count("_R1") + file_name.count("_R2") > 1:
            raise Exception(
                "File {} can't contain \"_R1\" or \"_R2\" (its read pair) more than once. Valid example: \"S1_R1.fast.gz\"".format(file_name)
            )

def get_common_name(match, match_index):
    start = match.start(match_index)
    end = match.end(match_index)

    original_string = match.string
    return "{}#{}".format(original_string[:start], original_string[end:])

def check_fastq_pairs_complete(files):
    file_names = [file.split("/")[-1] for file in files]

    file_map = defaultdict(lambda: {"reads": [], "file_names": []})

    for file_name in file_names:
        match = re.search(regex, file_name)

        match_index = 1 if match.group(1) else 2

        common_name = get_common_name(match, match_index)

        file_map[common_name]["reads"].append(int(match.group(match_index)))
        file_map[common_name]["file_names"].append(file_name)

    single_files = []

    for value in file_map.values():
        reads = value["reads"]
        file_names = value["file_names"]

        if sorted(reads) != [1, 2]:
            single_files += file_names

    if len(single_files) > 0:
        single_files_str =  "\n".join(single_files)
        raise Exception(
            """Some of your files do not have a matching read pair. Please ensure that, for each sublibrary, you have a pair of Fastq files with the same name except for _R1 or _R2\n
The following files are missing their read pair:\n
{}
""".format(single_files_str))

def check_script_version_is_latest(api_token, resume):
    response = http_get(
        "{}/cliUpload/latestScriptVersion".format(base_url),
        {"x-api-token": "Bearer {}".format(api_token)}
    )

    if response.status_code != 200:
        raise Exception("Failed to check the version of the script: {} {}".format(response.status_code, response.text))

    latest_version = response.json()["version"]

    outdated = SCRIPT_VERSION != latest_version

    if (outdated and not resume):
        raise Exception("The script you are using is outdated. Please download the latest version from the browser application")

def check_files_validity(files):
    # Take list of glob patterns and expand and flatten them into a list of files
    files_list = [file for glob_pattern in files for file in glob.glob(glob_pattern)]

    check_names_are_valid(files_list)
    check_fastq_pairs_complete(files_list)
    return files_list

# Performs all of the pre-upload validation and parameter checks
def prepare_upload(args):
    non_resumable_args = args.run_id or args.wt_files or args.immune_files

    if non_resumable_args and args.resume:
        raise Exception(
            "If resuming a previous upload, only -r / --resume flag and -t / --token are needed, nothing else is allowed"
        )

    if not args.token:
        raise Exception(
            "No token provided. Please specify the token with the --token option or the PARSE_CLOUD_TOKEN environment variable."
        )

    resume = args.resume or show_resume_option()

    if not resume:
        if not args.run_id:
            raise Exception("run_id is required")

        if not args.immune_files and not args.wt_files:
            raise Exception("At least one wt or immune file is required")

    check_script_version_is_latest(args.token, resume)

    threads_count = args.threads_count

    # If not defined by user, use heuristic based on cpu's count
    if (threads_count is None):
        threads_count = max(os.cpu_count() * 3, MIN_THREADS_COUNT)
        threads_count = min(threads_count, MAX_THREADS_COUNT)

    upload_tracker = None
    if resume:
        upload_tracker = UploadTracker.fromResumeFile(args.token, threads_count)
    else:
        files = {}
        if args.wt_files:
            wt_files = check_files_validity(args.wt_files)
            files["wtFastq"] = wt_files
        if args.immune_files:
            immune_files = check_files_validity(args.immune_files)
            files["immuneFastq"] = immune_files

        upload_tracker = UploadTracker.fromScratch(
            args.run_id, files, args.token, threads_count
        )

        if (not args.yes):
            show_files_to_upload_warning(upload_tracker.file_list)

    return upload_tracker

def store_error(e, filename):
    extra_data = ""

    if isinstance(e, urllib.error.HTTPError):
        try:
            extra_data = e.read().decode('utf-8')
            # Remove CanonicalRequestBytes and StringToSignBytes from the error output
            extra_data = re.sub(r'<CanonicalRequestBytes>.*?</CanonicalRequestBytes>', '', extra_data, flags=re.DOTALL)
            extra_data = re.sub(r'<StringToSignBytes>.*?</StringToSignBytes>', '', extra_data, flags=re.DOTALL)
        except Exception:
            pass

    try:
        current_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(filename, "a") as f:
            f.write(f"Time: {current_time}\n")
            f.write(str(e) + "\n")
            f.write(extra_data)
            f.write("\n")
            f.write("\n")
            f.write(traceback.format_exc())
            f.write("\n-------------------------------------")
            f.write("\n-------------------------------------\n")
    except Exception:
        print("Failed to store error log: ", e)
        # Avoid error handling errors interrupting the rest of the execution
        pass

def main():
    parser = argparse.ArgumentParser(description="Perform a multipart upload to S3.")
    parser.add_argument("-id", "--run_id", required=False, help="The run id")
    parser.add_argument(
        "-t",
        "--token",
        required=False,
        default=os.environ.get("PARSE_CLOUD_TOKEN"),
        help="The upload token, can be obtained from the browser application",
    )

    parser.add_argument(
        "--wt_files",
        nargs="*",
        required=False,
        help="A space-separated list of files. You can also select multiple files by using *. For example, path/to/files/*.fastq.gz will pick all files in the path that end with .fastq.gz",
    )
    parser.add_argument(
        "--immune_files",
        nargs="*",
        required=False,
        help="A space-separated list of files. You can also select multiple files by using *. For example, path/to/files/*.fastq.gz will pick all files in the path that end with .fastq.gz",
    )
    parser.add_argument(
        "-tc",
        "--threads_count",
        required=False,
        help="The amount of threads to be used for the upload",
        type=int,
        default=None,
    )
    parser.add_argument(
        "-r", "--resume", action="store_true", help="Resume an interrupted upload", required=False
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip prompts and pre-upload checks",
        required=False
    )

    args = parser.parse_args()

    try:
        cleanup_old_error_logs()

        upload_tracker = prepare_upload(args)

        upload_all_files(upload_tracker)
    except Exception as e:
        print()
        print("An error ocurred:")
        print(e)

        store_error(e, CLEAN_ERROR_PATH)
        print("\n")
        print("If you reach out to support, please provide the following files too: {}, {}".format(CLEAN_ERROR_PATH, REQUEST_ERROR_PATH))
        sys.exit(1)


if __name__ == "__main__":
    main()
