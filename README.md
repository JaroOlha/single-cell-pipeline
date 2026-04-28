# Genomics Transfer Scripts

This repository contains three simple scripts for transferring FASTQ data between:

- Illumina BaseSpace (via the `bs` CLI)
- Parse Biosciences Trailmaker (via the provided `parse-upload-1.1.1.py` script)

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

After successful authentication, a configuration file is created at:

```
~/.basespace/default.cfg
```

This file contains the authentication token.

---
<br />
<br />
<br />

# BaseSpace Download

Script:

```
BaseSpace_download.sh
```

Before running:

- Edit the script and insert the correct `PROJECT_ID`.

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

This will not be used in production, it is only used to generate test datasets.

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

## Step 2 — Generate Upload Token

Click **Refresh Token**.

You will see a command similar to:

```bash
python parse-upload-1.1.1.py \
  --token <TOKEN> \
  --run_id <RUN_ID> \
  --wt_files /path/to/file_1.fastq.gz /path/to/file_2.fastq.gz
```

---

## Step 3 — Modify File Paths

Replace the file paths with your local FASTQ directory:

```bash
python parse-upload-1.1.1.py \
  --token <TOKEN> \
  --run_id <RUN_ID> \
  --wt_files /fastq_folder/*.fastq.gz
```

Run from the directory containing `parse-upload-1.1.1.py`.

---
<br />
<br />
<br />

# Upload to NRP

**copy-pasteable commands** for a first-time user:
<br />
<br />

## Step 1: Configure repository (one-time)
```
nrp-cmd add repository https://workflow-repo.test.du.cesnet.cz/ wfrepo
```

## Step 2: Create record
```
nrp-cmd create record '{"title": "SC-test-cli"}' \
  --repository wfrepo \
  --community generic \
  --set r
```

## Step 3: Upload all files from a directory
```
for f in ./trailmaker_files/*; do
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