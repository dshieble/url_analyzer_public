#!/bin/bash

# Get current timestamp
timestamp=$(date +"%Y-%m-%d_%H-%M-%S")

# Define file path
filepath="data/openphish/${timestamp}.txt"

# Use curl to download the file
curl -o "$filepath" https://www.openphish.com/feed.txt

# Check if the download was successful
if [ $? -eq 0 ]; then
    echo "File downloaded successfully and saved as $filepath"
else
    echo "Failed to download the file."
fi