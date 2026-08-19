# Genomics Transfer Scripts

Scripts and instructions for transferring FASTQ data between:

- **Illumina BaseSpace** (via the `bs` CLI)
- **Parse Biosciences Trailmaker** (via the downloadable `parse-upload-x.x.x.py` script)
- **Invenio RDM repository** (via the `nrp-cmd` client)

## Workflow overview

1. Download FASTQ files from BaseSpace.
2. Upload the FASTQ files to Trailmaker for processing.
3. Download the processed results from Trailmaker.
4. Upload the results to the NRP (Invenio) repository.

---

## Prerequisites

### BaseSpace CLI

Download the BaseSpace CLI and authenticate:

```bash
wget "https://launch.basespace.illumina.com/CLI/latest/amd64-linux/bs" -O bs
chmod u+x bs
./bs auth
```

You will receive a URL in the terminal. Open it in a browser, authenticate, and approve access.

After successful authentication, a configuration file containing the authentication token is created at:

```text
~/.basespace/default.cfg
```

### nrp-cmd

`nrp-cmd` is a command-line client for Invenio repositories. See [installation with pip & virtualenv or uvx](https://nrp-cz.github.io/docs/userguide/commandline#installation).

If you installed `nrp-cmd` with `pip` & `virtualenv`, activate the virtual environment before use:

```bash
source nrp-cmd/bin/activate
```

### NRP repository access

Before uploading to NRP, register or log in at the [repository website](https://datarepo.eosc.cz/) and generate a token in your profile under **Settings → Applications**.

---

## BaseSpace download

```bash
mv bs scripts/bs
./scripts/BaseSpace_download.sh
```

The script will prompt for a project ID and download all data associated with the specified BaseSpace project.

---

## BaseSpace upload (testing only)

> **Note:** This script is not intended for production use. It exists only to create test datasets for validating the download workflow.

### FASTQ naming requirements

Files must follow BaseSpace naming conventions:

```text
SampleName_S1_L001_R1_001.fastq.gz
SampleName_S1_L001_R2_001.fastq.gz
```

### Running the upload

1. Open `BaseSpace_upload.sh` and set the correct `PROJECT_ID`.
2. Set the correct local FASTQ directory.
3. Run the script:

```bash
./BaseSpace_upload.sh
```

---

## Trailmaker upload

Uploads are performed using the script provided by Trailmaker via the web UI.

### 1. Create a run

> **Note:** In production, this will be done by the researcher who knows the sequencing experiment.

1. Go to <https://app.trailmaker.parsebiosciences.com/pipeline>.
2. Click **Create New Run**. A dialog window will open where you can provide experimental details (experimental setup, sample loading table, reference genome, etc.).
   - If you only want to upload the FASTQ files for now, close the window — the experimental details can be added after the data upload.
3. Click the edit button next to **Fastq files** and select **Console Upload**.

### 2. Download the upload script

Download or copy the `parse-upload-x.x.x.py` script.

### 3. Generate an upload token

Click **Refresh Token**. You will see a command similar to:

```bash
python parse-upload-x.x.x.py \
  --token <TOKEN> \
  --run_id <RUN_ID> \
  --wt_files /path/to/file_1.fastq.gz /path/to/file_2.fastq.gz
```

### 4. Modify file paths

Navigate to the directory containing `parse-upload-x.x.x.py` and replace the file paths with your local FASTQ directory:

```bash
python parse-upload-x.x.x.py \
  --token <TOKEN> \
  --run_id <RUN_ID> \
  --wt_files /fastq_directory/*.fastq.gz
```

> **Note:** The `parse-upload-x.x.x.py` script is constantly updated. If you encounter an error when uploading to Trailmaker, download the latest version from their site.

---

## Trailmaker download

Trailmaker does not provide an API. Download the dataset manually through the web client to your local machine, then upload it to the Invenio repository — either manually or with the `nrp-cmd` commands in the **Upload to NRP** section.

### 1. Open the Insights module

Navigate to the `Insights` module on the left side of the page.

### 2. Download the AnnData/Seurat object

Click `Download` and select `.h5ad/.rds` (depending on the project settings) and `.txt` for `Data Processing settings`.

### 3. Download the pre-processed files

Click on `Parse Evercode™` and select the green `Upload` button under all three files:

- `count_matrix.mtx` / `DGE.mtx`
- `cell_metadata.csv`
- `all_genes.csv`

Depending on the project, there may be many samples, but they all contain the same three files — download them only once.

---

## Upload to NRP

### 1. Add a repository (one-time)

```bash
nrp-cmd add repository https://datarepo.eosc.cz/ <repository-alias>
```

Paste your token when prompted.

### 2. Create a record

```bash
nrp-cmd create record '{"title": "Name-of-your-record"}' \
  --repository <repository-alias> \
  --workflow individual \
  --set r
```

### 3. Upload files

Upload all files from a directory:

```bash
for f in ./path-to-your-dataset/*; do
  [ -f "$f" ] && nrp-cmd upload file @r "$f" --repository <repository-alias> --draft
done
```

Or upload a single file:

```bash
nrp-cmd upload file @r <file> --repository <repository-alias>
```

### 4. Publish (optional)

```bash
nrp-cmd publish record @r --repository <repository-alias>
```

---

For full CLI documentation, visit [nrp-cz.github.io](https://nrp-cz.github.io/docs/userguide/commandline).
