import os
import requests
import shutil
import zipfile
from tqdm import tqdm
import json
from difflib import get_close_matches
import re
import platform
import datetime
import time
import tempfile

MANGADEX_API = "https://api.mangadex.org"

def sanitize_filename(filename):
    # Replace invalid characters with underscores
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', filename)
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip('. ')
    return sanitized

def search_manga(title):
    try:
        # First try exact search
        response = requests.get(f"{MANGADEX_API}/manga", params={
            "title": title,
            "limit": 100,
            "order[relevance]": "desc"
        })
        response.raise_for_status()
        data = response.json()
        
        if not data["data"]:
            # If no results, try a broader search
            response = requests.get(f"{MANGADEX_API}/manga", params={
                "title": title,
                "limit": 100,
                "order[relevance]": "desc",
                "contentRating[]": ["safe", "suggestive", "erotica", "pornographic"]
            })
            response.raise_for_status()
            data = response.json()
        
        if not data["data"]:
            raise Exception(f"No manga found with title '{title}'")
        
        # Save the raw search results to a temporary file for debugging
        temp_dir = tempfile.gettempdir()
        debug_file = os.path.join(temp_dir, "mangadex_search_debug.json")
        with open(debug_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\nDebug: Search results saved to {debug_file}")
        
        # Get all titles for matching
        titles = []
        seen_entries = {}  # Dictionary to track unique entries
        
        for manga in data["data"]:
            manga_id = manga["id"]
            manga_title = manga["attributes"]["title"].get("en", list(manga["attributes"]["title"].values())[0])
            # Get description and truncate it
            description = manga["attributes"]["description"].get("en", "")
            if not description:
                description = list(manga["attributes"]["description"].values())[0] if manga["attributes"]["description"] else ""
            truncated_desc = (description[:70] + "...") if len(description) > 70 else description
            
            titles.append((manga_title, manga, manga_id, truncated_desc))

        
        # Find closest matches
        matches = get_close_matches(title.lower(), [t[0].lower() for t in titles], n=5, cutoff=0.3)
        
        if not matches:
            # If no close matches, show the first 5 results
            matches = [t[0] for t in titles[:5]]
        
        # Create a set to track displayed manga IDs
        displayed_ids = set()
        displayed_manga = []  # Store the manga objects in display order
        
        print("\nSearch results:")
        for i, match in enumerate(matches, 1):
            for title, manga, manga_id, desc in titles:
                if title.lower() == match.lower() and manga_id not in displayed_ids:
                    print(f"{i}. {title} - {desc}")
                    displayed_ids.add(manga_id)
                    displayed_manga.append(manga)  # Store the manga object
                    break
        
        while True:
            try:
                choice = input("\nEnter the number of the manga you want to download (or 'q' to quit): ")
                if choice.lower() == 'q':
                    raise Exception("Search cancelled by user")
                
                choice = int(choice)
                if 1 <= choice <= len(displayed_manga):
                    return displayed_manga[choice - 1]  # Return the manga object directly
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a valid number or 'q' to quit.")
    
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error connecting to MangaDex API: {str(e)}")
    except json.JSONDecodeError:
        raise Exception("Error parsing response from MangaDex API")
    except Exception as e:
        raise Exception(f"Error searching for manga: {str(e)}")

def get_manga_metadata(manga):
    attributes = manga["attributes"]
    title = attributes["title"].get("en", list(attributes["title"].values())[0])
    description = attributes["description"].get("en", "No description.")
    tags = [t["attributes"]["name"].get("en", "") for t in manga["relationships"] if t["type"] == "tag"]
    
    authors = []
    for rel in manga["relationships"]:
        if rel["type"] in ["author", "artist"]:
            try:
                res = requests.get(f"{MANGADEX_API}/{rel['type']}/{rel['id']}").json()
                if "data" in res and "attributes" in res["data"]:
                    name = res["data"]["attributes"]["name"]
                    authors.append(name)
            except (requests.exceptions.RequestException, KeyError, json.JSONDecodeError) as e:
                print(f"Warning: Could not fetch {rel['type']} information: {str(e)}")
                continue

    return {
        "title": title,
        "description": description,
        "authors": authors,
        "tags": tags,
        "id": manga["id"]
    }

def download_cover(manga_id, output_dir):
    response = requests.get(f"{MANGADEX_API}/cover", params={"manga[]": manga_id})
    response.raise_for_status()
    covers = response.json()["data"]
    if not covers:
        return None
    cover_file = covers[0]["attributes"]["fileName"]
    url = f"https://uploads.mangadex.org/covers/{manga_id}/{cover_file}"
    output_path = os.path.join(output_dir, "cover.jpg")
    img_data = requests.get(url).content
    with open(output_path, "wb") as f:
        f.write(img_data)
    return output_path

def get_chapters(manga_id, translated_language="en"):
    chapters = []
    offset = 0
    limit = 100
    while True:
        params = {
            "manga": manga_id,
            "translatedLanguage[]": translated_language,
            "limit": limit,
            "offset": offset,
            "order[chapter]": "asc",
            "includes[]": ["scanlation_group"]
        }
        response = requests.get(
            f"{MANGADEX_API}/chapter",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        chapters.extend(data["data"])
        if len(chapters) >= data["total"]:
            break
        offset += limit

    # Filter out external links and group chapters by chapter number
    chapter_groups = {}
    for chapter in chapters:
        # Skip if it's an external link
        if chapter["attributes"].get("externalUrl"):
            continue
        chapter_num = chapter["attributes"]["chapter"]
        if chapter_num not in chapter_groups:
            chapter_groups[chapter_num] = []
        chapter_groups[chapter_num].append(chapter)

    # Find all unique scanlation groups
    all_groups = set()
    for versions in chapter_groups.values():
        for version in versions:
            for rel in version["relationships"]:
                if rel["type"] == "scanlation_group":
                    group_name = rel["attributes"]["name"] if "attributes" in rel else "Unknown"
                    all_groups.add(group_name)

    # If there are multiple groups, ask user to choose one
    preferred_group = None
    if len(all_groups) > 1:
        print("\nMultiple scanlation groups found:")
        groups_list = sorted(list(all_groups))
        for i, group in enumerate(groups_list, 1):
            print(f"{i}. {group}")
        
        while True:
            try:
                choice = input("\nEnter the number of your preferred scanlation group (or press Enter to choose per chapter): ")
                if not choice.strip():
                    break
                
                choice = int(choice)
                if 1 <= choice <= len(groups_list):
                    preferred_group = groups_list[choice - 1]
                    print(f"Selected group: {preferred_group}")
                    break
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a valid number or press Enter to choose per chapter.")

    # Select chapters based on preferred group or ask per chapter
    selected_chapters = []
    for chapter_num, versions in chapter_groups.items():
        if len(versions) == 1:
            selected_chapters.append(versions[0])
            continue

        if preferred_group:
            # Try to find version from preferred group
            preferred_version = None
            for version in versions:
                for rel in version["relationships"]:
                    if rel["type"] == "scanlation_group":
                        group_name = rel["attributes"]["name"] if "attributes" in rel else "Unknown"
                        if group_name == preferred_group:
                            preferred_version = version
                            break
                if preferred_version:
                    break
            
            if preferred_version:
                selected_chapters.append(preferred_version)
                continue

        # If no preferred group or preferred group not found for this chapter, show options
        print(f"\nMultiple versions found for Chapter {chapter_num}:")
        for i, version in enumerate(versions, 1):
            group_name = "Unknown"
            for rel in version["relationships"]:
                if rel["type"] == "scanlation_group":
                    group_name = rel["attributes"]["name"] if "attributes" in rel else "Unknown"
                    break
            
            print(f"{i}. Group: {group_name}")
            print(f"   Pages: {version['attributes']['pages']}")
            print(f"   Uploaded: {version['attributes']['createdAt']}")
            print(f"   Version: {version['attributes'].get('version', 1)}")

        while True:
            try:
                choice = input(f"\nSelect version for Chapter {chapter_num} (1-{len(versions)}, or 's' to skip): ")
                if choice.lower() == 's':
                    print(f"Skipping Chapter {chapter_num}")
                    break
                
                choice = int(choice)
                if 1 <= choice <= len(versions):
                    selected_chapters.append(versions[choice - 1])
                    break
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a valid number or 's' to skip.")

    return selected_chapters

def download_chapter(chapter_id, chapter_title, output_dir, progress_callback=None):
    start_time = time.time()
    total_bytes = 0
    
    at_home = requests.get(f"{MANGADEX_API}/at-home/server/{chapter_id}")
    at_home.raise_for_status()
    base_url = at_home.json()["baseUrl"]
    chapter_data = at_home.json()["chapter"]

    image_dir = os.path.join(output_dir, chapter_title)
    os.makedirs(image_dir, exist_ok=True)

    for i, file_name in enumerate(chapter_data["data"]):
        image_url = f"{base_url}/data/{chapter_data['hash']}/{file_name}"
        img_data = requests.get(image_url).content
        total_bytes += len(img_data)
        img_path = os.path.join(image_dir, f"{i:03d}.jpg")
        with open(img_path, "wb") as f:
            f.write(img_data)
        if progress_callback:
            progress_callback()

    end_time = time.time()
    download_time = end_time - start_time
    download_speed = total_bytes / download_time if download_time > 0 else 0
    
    return image_dir, {
        "download_time": download_time,
        "total_bytes": total_bytes,
        "download_speed": download_speed,
        "pages": len(chapter_data["data"])
    }

def create_cbz(image_dir, output_path, metadata=None):
    with zipfile.ZipFile(output_path, "w") as cbz:
        for filename in sorted(os.listdir(image_dir)):
            file_path = os.path.join(image_dir, filename)
            cbz.write(file_path, arcname=filename)
        if metadata:
            meta_path = os.path.join(image_dir, "metadata.txt")
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(metadata, indent=2, ensure_ascii=False))
            cbz.write(meta_path, arcname="metadata.txt")

def clear_console():
    """Clear the console screen based on the operating system."""
    if platform.system() == 'Windows':
        os.system('cls')
    else:
        os.system('clear')

def check_chapter_availability(manga_id, translated_language="en"):
    """Check if all chapters are available in the specified language."""
    try:
        # Get all chapters in the specified language
        chapters = []
        offset = 0
        limit = 100
        while True:
            params = {
                "manga": manga_id,
                "translatedLanguage[]": translated_language,
                "limit": limit,
                "offset": offset,
                "order[chapter]": "asc"
            }
            response = requests.get(
                f"{MANGADEX_API}/chapter",
                params=params
            )
            response.raise_for_status()
            data = response.json()
            chapters.extend(data["data"])
            if len(chapters) >= data["total"]:
                break
            offset += limit

        # Get all chapters regardless of language
        all_chapters = []
        offset = 0
        while True:
            params = {
                "manga": manga_id,
                "limit": limit,
                "offset": offset,
                "order[chapter]": "asc"
            }
            response = requests.get(
                f"{MANGADEX_API}/chapter",
                params=params
            )
            response.raise_for_status()
            data = response.json()
            all_chapters.extend(data["data"])
            if len(all_chapters) >= data["total"]:
                break
            offset += limit

        # Find chapters not available in the preferred language
        translated_chapter_nums = {ch["attributes"]["chapter"] for ch in chapters}
        all_chapter_nums = {ch["attributes"]["chapter"] for ch in all_chapters}
        missing_chapters = sorted(all_chapter_nums - translated_chapter_nums)

        if missing_chapters:
            print(f"\nNote: The following chapters are not available in {translated_language}:")
            for chapter in missing_chapters:
                print(f"  • Chapter {chapter}")
            print("\nThis is normal for some manga series where certain chapters:")
            print("  • May be split into subchapters (e.g., 356.1, 356.2 instead of 356)")
            print("  • May be available in other languages but not in English")
            print("  • May be special chapters or extras")
            print("\nThe download will continue with the available chapters.")
            return missing_chapters
        return []

    except requests.exceptions.RequestException as e:
        raise Exception(f"Error checking chapter availability: {str(e)}")
    except json.JSONDecodeError:
        raise Exception("Error parsing response from MangaDex API")

def extract_chapter(chapter_path, temp_dir):
    """Extract a chapter CBZ file to a temporary directory and rename files with chapter prefix."""
    # Extract chapter number from filename (assuming format like "Chapter 12.1.cbz" or "12.1.cbz")
    chapter_name = os.path.splitext(os.path.basename(chapter_path))[0]
    # Extract both the main chapter number and decimal part if it exists
    match = re.match(r'Chapter_(\d+)(?:\.(\d+))?', chapter_name)
    if not match:
        raise Exception(f"Could not extract chapter number from filename: {chapter_name}")
    
    main_num = match.group(1)
    decimal_part = match.group(2) if match.group(2) else "0"
    
    # Pad main chapter number to 3 digits and keep decimal part
    chapter_num = f"{int(main_num):03d}.{decimal_part}"
    
    with zipfile.ZipFile(chapter_path, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            if file_info.filename.lower() == 'metadata.txt':
                continue
                
            # Get the file extension and base name
            base_name = os.path.basename(file_info.filename)
            name, ext = os.path.splitext(base_name)
            
            # Create new filename with chapter prefix
            new_name = f"{chapter_num}{name}{ext}"
            new_path = os.path.join(temp_dir, new_name)
            
            # Extract and rename the file
            with zip_ref.open(file_info) as source, open(new_path, 'wb') as target:
                shutil.copyfileobj(source, target)

def combine_chapters(manga_dir, output_path):
    """Combine all chapter CBZ files into a single CBZ file."""
    chapter_files = []
    for file in os.listdir(manga_dir):
        if file.endswith('.cbz'):
            chapter_files.append(file)
    chapter_files = sorted(chapter_files)
    
    if not chapter_files:
        raise Exception("No chapter files found in the selected manga directory")

    print(f"\nFound {len(chapter_files)} chapters to combine")
    
    # Create a temporary directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create the output CBZ file
        with zipfile.ZipFile(output_path, 'w') as output_cbz:
            # Process each chapter
            for chapter_file in tqdm(chapter_files, desc="Combining chapters"):
                chapter_path = os.path.join(manga_dir, chapter_file)
                chapter_temp_dir = os.path.join(temp_dir, os.path.splitext(chapter_file)[0])
                os.makedirs(chapter_temp_dir, exist_ok=True)
                
                # Extract chapter
                extract_chapter(chapter_path, chapter_temp_dir)
                
                # Add all files from the chapter to the output CBZ
                for root, _, files in os.walk(chapter_temp_dir):
                    for file in sorted(files):
                        if file.lower() == 'metadata.txt':
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, chapter_temp_dir)
                        output_cbz.write(file_path, arcname)

def get_chapter_files(manga_dir):
    """Get all chapter files from the manga directory and sort them properly."""
    chapter_files = []
    for file in os.listdir(manga_dir):
        if file.endswith('.cbz'):
            chapter_files.append(file)
    
    # Sort chapters numerically, handling decimal chapter numbers
    def chapter_key(filename):
        # Extract chapter number from filename
        match = re.match(r'Chapter_(\d+)(?:\.(\d+))?', os.path.splitext(filename)[0])
        if match:
            main_num = int(match.group(1))
            decimal_part = int(match.group(2)) if match.group(2) else 0
            return (main_num, decimal_part)
        return (0, 0)  # Default for files that don't match the pattern
    
    return sorted(chapter_files, key=chapter_key)

def get_downloaded_chapters(output_base):
    """Get a list of already downloaded chapters."""
    downloaded = set()
    for file in os.listdir(output_base):
        if file.endswith('.cbz') and not file.endswith('_combined.cbz'):
            # Extract chapter number from filename
            match = re.match(r'Chapter_(\d+\.?\d*)', file)
            if match:
                downloaded.add(match.group(1))
    return downloaded

def main():
    try:
        manga_name = input("Enter manga name: ")
        manga = search_manga(manga_name)
        manga_id = manga["id"]
        metadata = get_manga_metadata(manga)
        
        # Create downloads directory if it doesn't exist
        downloads_dir = os.path.abspath("./downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Sanitize the manga title for use as directory name
        safe_title = sanitize_filename(metadata["title"])
        output_base = os.path.join(downloads_dir, safe_title)
        os.makedirs(output_base, exist_ok=True)

        # Check for existing download
        downloaded_chapters = get_downloaded_chapters(output_base)
        if downloaded_chapters:
            print(f"\nFound {len(downloaded_chapters)} previously downloaded chapters:")
            for chapter in sorted(downloaded_chapters):
                print(f"  • Chapter {chapter}")
            
            while True:
                choice = input("\nWould you like to:\n1. Resume download (skip existing chapters)\n2. Start fresh (delete existing chapters)\n3. Quit\nEnter your choice (1-3): ")
                if choice in ['1', '2', '3']:
                    break
                print("Please enter 1, 2, or 3")
            
            if choice == '2':
                # Delete existing chapters
                for file in os.listdir(output_base):
                    if file.endswith('.cbz') and not file.endswith('_combined.cbz'):
                        os.remove(os.path.join(output_base, file))
                downloaded_chapters = set()
            elif choice == '3':
                print("\nDownload cancelled by user.")
                return

        # Save metadata JSON to root folder
        with open(os.path.join(output_base, "manga_metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # Download cover if it doesn't exist
        cover_path = os.path.join(output_base, "cover.jpg")
        if not os.path.exists(cover_path):
            cover_path = download_cover(manga_id, output_base)
            if cover_path:
                print(f"Saved cover to {cover_path}")

        # Check if all chapters are available in English
        missing_chapters = check_chapter_availability(manga_id)
        if missing_chapters:
            while True:
                choice = input("\nSome chapters are not available in English. Would you like to continue anyway? (y/n): ").lower()
                if choice in ['y', 'n']:
                    break
                print("Please enter 'y' or 'n'")
            
            if choice == 'n':
                print("\nDownload cancelled by user.")
                return

        # Get and download chapters
        chapters = get_chapters(manga_id)
        total_chapters = len(chapters)
        
        if total_chapters == 0:
            print("No chapters found to download.")
            return

        # Initialize download statistics
        download_stats = {
            "download_date": datetime.datetime.now().isoformat(),
            "total_chapters": total_chapters,
            "chapters": [],
            "total_download_time": 0,
            "total_bytes": 0,
            "average_speed": 0,
            "scanlation_groups": set()
        }
        
        # Load existing download stats if available
        stats_path = os.path.join(output_base, "download_stats.json")
        if os.path.exists(stats_path):
            try:
                with open(stats_path, "r", encoding="utf-8") as f:
                    existing_stats = json.load(f)
                    download_stats["total_download_time"] = existing_stats.get("total_download_time", 0)
                    download_stats["total_bytes"] = existing_stats.get("total_bytes", 0)
                    download_stats["chapters"] = existing_stats.get("chapters", [])
                    download_stats["scanlation_groups"] = set(existing_stats.get("scanlation_groups", []))
            except Exception as e:
                print(f"Warning: Could not load existing download stats: {e}")
        
        for i, ch in enumerate(chapters, 1):
            clear_console()  # Clear console before starting new chapter
            print(f"\nManga: {metadata['title']}")
            print("--------------------------------")
            chapter_number = ch["attributes"].get("chapter", "0")
            # Format chapter number with leading zeros and preserve decimal part
            chapter_title = f"Chapter_{float(chapter_number):03.1f}".replace(" ", "_")
            
            # Skip if chapter is already downloaded
            if chapter_number in downloaded_chapters:
                print(f"Skipping {chapter_title} (already downloaded)")
                continue
                
            print(f"Processing {chapter_title} ({i}/{total_chapters})")

            try:
                # Create chapter progress bar at position 1
                chapter_progress = tqdm(total=ch["attributes"]["pages"], desc=f"Chapter {chapter_number}", position=0, leave=True)
                
                def update_chapter_progress(*args):
                    chapter_progress.update(1)
                
                image_dir, download_info = download_chapter(ch["id"], chapter_title, output_base, progress_callback=update_chapter_progress)
                cbz_path = os.path.join(output_base, f"{chapter_title}.cbz")
                create_cbz(image_dir, cbz_path, metadata=metadata)
                shutil.rmtree(image_dir)
                
                # Close chapter progress bar
                chapter_progress.close()
                
                # Update download statistics
                download_stats["total_download_time"] += download_info["download_time"]
                download_stats["total_bytes"] += download_info["total_bytes"]
                
                # Get scanlation group info
                scanlation_group = "Unknown"
                for rel in ch["relationships"]:
                    if rel["type"] == "scanlation_group":
                        scanlation_group = rel["attributes"]["name"] if "attributes" in rel else "Unknown"
                        download_stats["scanlation_groups"].add(scanlation_group)
                        break
                
                # Add chapter info to stats
                chapter_info = {
                    "chapter_number": chapter_number,
                    "title": chapter_title,
                    "download_time": download_info["download_time"],
                    "bytes": download_info["total_bytes"],
                    "speed": download_info["download_speed"],
                    "pages": download_info["pages"],
                    "scanlation_group": scanlation_group
                }
                download_stats["chapters"].append(chapter_info)
                
                # Save stats after each successful download
                with open(stats_path, "w", encoding="utf-8") as f:
                    json.dump(download_stats, f, indent=2, ensure_ascii=False)
                
            except Exception as e:
                print(f"Failed to process {chapter_title}: {e}")
                raise  # Re-raise the exception to trigger cleanup

        # Calculate average speed
        if download_stats["total_download_time"] > 0:
            download_stats["average_speed"] = download_stats["total_bytes"] / download_stats["total_download_time"]
        
        # Convert scanlation_groups set to list for JSON serialization
        download_stats["scanlation_groups"] = list(download_stats["scanlation_groups"])
        
        # Save final download statistics
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(download_stats, f, indent=2, ensure_ascii=False)

        # Combine all chapters into a single CBZ file
        print("\nCombining all chapters into a single CBZ file...")
        combined_cbz_path = os.path.join(output_base, f"{safe_title}_combined.cbz")
        combine_chapters(output_base, combined_cbz_path)
        
        # Clean up individual chapter CBZ files
        for file in os.listdir(output_base):
            if file.endswith('.cbz') and not file.endswith('_combined.cbz'):
                os.remove(os.path.join(output_base, file))

        print("\nDone! Combined CBZ file created successfully.")

    except Exception as e:
        print(f"\nAn error occurred during download: {str(e)}")
        print("Cleaning up download folder...")
        try:
            if 'output_base' in locals() and os.path.exists(output_base):
                shutil.rmtree(output_base)
                print(f"Successfully removed download folder: {output_base}")
        except Exception as cleanup_error:
            print(f"Error during cleanup: {str(cleanup_error)}")
        raise  # Re-raise the original exception

if __name__ == "__main__":
    main()
