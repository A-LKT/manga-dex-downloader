a handful of script to download manga from mangadex api. CLI-based, nothing fancy but get's the job done.

NOTE: use at your own risk. I take no responsibility for the code or the way you use it.
These scripts were built solely for educational purposes.

1. downloader.py
    - let's you provide a string and searches for the manga by name partial match.
    - if found let's you select one to download
    - will give you the option to select scan group if multiple available
    - will only download english chapters
    - will inform if some chapters missing in english language
    - once all downloaded will zip into a single CBZ file for easier portability

2. chapter_combiner_external.py
   - will try to figure out the names of the chapters and convert them into a single uniform sequence

3. splitter.py
   - splits CBZs larger than 3.5 GB into multiple numbered files
