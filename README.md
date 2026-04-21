# Genomics Transfer Scripts

This repository contains three simple scripts for transferring FASTQ data between:

- Illumina BaseSpace (via the `bs` CLI)
- Parse Biosciences Trailmaker (via the provided `parse-upload-1.1.1.py` script)

The BaseSpace upload script exists only to generate test data for validating the download workflow.



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

# Upload to NRP

Script:

```
nrp_upload.sh
```

Uploads datasets (single files or directories) to an NRP InvenioRDM repository and optionally publishes them.

## Prerequisites

Install `nrp-cmd`:

```bash
curl -O https://raw.githubusercontent.com/NRP-CZ/nrp-cmd/main/nrp-cmd && chmod +x nrp-cmd && sudo mv nrp-cmd /usr/local/bin/
```

On first run, `nrp-cmd` will prompt you to authenticate with your NRP account.  
If authentication fails, remove `~/.nrp/` and re-run to start fresh.

## Options

| Flag | Argument | Default | Description |
|------|----------|---------|-------------|
| `-r` | `<alias>` | `wfrepo` | Repository alias |
| `-c` | `<community>` | `generic` | Community to publish into |
| `-p` | — | off | Auto-publish after upload |
| `-d` | `<text>` | — | Description (optional) |
| `-h` | — | — | Print help and exit |

Positional arguments (required, in order): `<title>` `<file_or_directory>`

## Usage Examples

**Minimal — single file, draft only:**
```bash
./nrp_upload.sh "My Dataset" ./path/to/single_file
```

**Directory upload with auto-publish:**
```bash
./nrp_upload.sh -p "My Dataset" ./path/to/directory/
```

**Custom repository and community:**
```bash
./nrp_upload.sh -r myrepo -c myproject "SC Analysis Dataset" ./trailmaker_files/
```

**Full options — description, community, and auto-publish:**
```bash
./nrp_upload.sh -p -d "Single cell RNA-seq data from Trailmaker pipeline" -c myproject "SC Data" ./data.zip
```
---
