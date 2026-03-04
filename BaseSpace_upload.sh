#!/bin/bash
#PBS -N BaseSpace_upload
#PBS -l select=1:ncpus=4:mem=128gb
#PBS -l walltime=24:00:00
#PBS -m ae

cd /storage/brno2/home/xolha/FRC_script_tests/
./bs upload dataset --project 490396907 ./raw_fastq_upload/*.fastq.gz > upload.log 2>&1
