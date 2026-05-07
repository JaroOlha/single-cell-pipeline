# Genomics Transfer Scripts

This repository contains simple scripts for transferring FASTQ data between:

- Illumina BaseSpace (via the `bs` CLI)
- Parse Biosciences Trailmaker (via the downloadable `parse-upload-x.x.x.py` script)
- Invenio RDM repository (via `nrp-cmd` client)

The BaseSpace upload script exists only to generate test data for validating the download workflow.
<br />
<br />
<br />

# Prerequisites

## BaseSpace CLI Installation and Authentication

Download the BaseSpace CLI:

```bash
wget "https://launch.basespace.illumina.com/CLI/latest/amd64-linux/bs" -O bs
chmod u+x bs
./bs auth
```

You will receive a URL in the terminal.  
Open it in a browser, authenticate, and approve access.

After successful authentication, a configuration file is created containing authentication token at:

```
~/.basespace/default.cfg
```


## nrp-cmd - commandline client for invenio repositories

[Installation with pip & virtualenv or uvx](https://nrp-cz.github.io/docs/userguide/commandline#installation)

---
<br />
<br />
<br />

# BaseSpace Download

Run:

```bash
./BaseSpace_download.sh
```

The script will download all data associated with the specified BaseSpace project.

---
<br />
<br />

# BaseSpace Upload (Testing Only)

Script:

```
BaseSpace_upload.sh
```

This is not intented be used in production, it is only used to create test datasets.

## FASTQ Naming Requirements

Files must follow BaseSpace naming conventions:

```
SampleName_S1_L001_R1_001.fastq.gz
SampleName_S1_L001_R2_001.fastq.gz
```

Before running:

- Insert the correct `PROJECT_ID`
- Insert the correct local FASTQ directory

Run:

```bash
./BaseSpace_upload.sh
```

---
<br />
<br />
<br />

# Trailmaker Upload

Uploads are performed using the script provided by Trailmaker via the web UI.

## Step 1 — Create a Run

Note: in production, this will be done by the researcher who knows the sequencing experiment.

Go to:

```
https://app.trailmaker.parsebiosciences.com/pipeline
```

Then:

1. Click **Create New Run**.
2. A dialog window will open where you can provide experimental details (experimental setup, sample loading table, reference genome, etc.).

If you only want to upload the FASTQ files for now, close the window -- the experimental details can be added after data upload.

3. Click the edit button next to **Fastq files** and select **Console Upload**.

---
<br />

## Step 2 - Download the upload script
Download / copy the `parse-upload-x.x.x.py` script.

---
<br />

## Step 3 — Generate Upload Token

Click **Refresh Token**.

You will see a command similar to:

```bash
python parse-upload-x.x.x.py \
  --token <TOKEN> \
  --run_id <RUN_ID> \
  --wt_files /path/to/file_1.fastq.gz /path/to/file_2.fastq.gz
```

---
<br />

## Step 4 — Modify File Paths

Replace the file paths with your local FASTQ directory:

```bash
python parse-upload-x.x.x.py \
  --token <TOKEN> \
  --run_id <RUN_ID> \
  --wt_files /fastq_folder/*.fastq.gz
```

Run from the directory containing `parse-upload-x.x.x.py`.

Disclaimer:
`parse-upload-x.x.x.py` script is being constantly updated. If you encounter an error when uploading to Trailmaker, download the latest version from their site.

---
<br />
<br />
<br />

# Upload to NRP
Before you start uploading to NRP, you need to register / login at the repository [website](https://workflow-repo.test.du.cesnet.cz/) and generate a token in your profile `Settings` -> `Applications`
<br />
<br />

**Copy-pasteable commands for a first-time user:**
<br />

## Step 1: Add a repository (one-time)
```
nrp-cmd add repository https://workflow-repo.test.du.cesnet.cz/ wfrepo
```
Paste your token when prompted.
## Step 2: Create record
```
nrp-cmd create record '{"title": "Name-of-your-record"}' \
  --repository wfrepo \
  --community generic \
  --set r
```

## Step 3: Upload all files from a directory
```
# define path to your dataset
for f in ./path-to-your-dataset/*; do
  [ -f "$f" ] && nrp-cmd upload file @r "$f" --repository wfrepo
done

# Or just a single file
nrp-cmd upload file @r <file>
```
## Step 4: Publish (optional)
```
nrp-cmd publish record @r --repository wfrepo
```
<br />
<br />

**For full CLI documentation visit [nrp-cz.github.io](https://nrp-cz.github.io/docs/userguide/commandline)**
