import os
import zipfile
import json
from tqdm import tqdm
import shutil
import tempfile
from difflib import get_close_matches
import re

def clear_console():
    """Clear the console screen based on the operating system."""
    if os.name == 'nt':  # Windows
        os.system('cls')
    else:
        os.system('clear')

def get_manga_directories(source_dir):
    """Get all manga directories from the source directory."""
    manga_dirs = []
    for item in os.listdir(source_dir):
        full_path = os.path.join(source_dir, item)
        if os.path.isdir(full_path):
            # Check if directory contains any subdirectories (chapters)
            if any(os.path.isdir(os.path.join(full_path, subdir)) for subdir in os.listdir(full_path)):
                # Check if combined CBZ already exists
                combined_cbz = os.path.join(source_dir, f"{item}_combined.cbz")
                manga_dirs.append((item, os.path.exists(combined_cbz)))
    return manga_dirs

def select_manga(manga_dirs):
    """Let user select a manga from the list of directories."""
    if not manga_dirs:
        raise Exception("No manga directories found in the source directory")

    print("\nAvailable manga:")
    for i, (manga, is_combined) in enumerate(manga_dirs, 1):
        status = " [Already Combined]" if is_combined else ""
        print(f"{i}. {manga}{status}")

    while True:
        try:
            choice = input("\nEnter the number of the manga you want to combine (or 'q' to quit): ")
            if choice.lower() == 'q':
                raise Exception("Operation cancelled by user")
            
            choice = int(choice)
            if 1 <= choice <= len(manga_dirs):
                return manga_dirs[choice - 1][0]  # Return just the manga name
            else:
                print("Invalid choice. Please try again.")
        except ValueError:
            print("Please enter a valid number or 'q' to quit.")

def extract_chapter_number(dirname):
    """Extract chapter number from directory name."""
    # Try different patterns in order of preference
    
    # Pattern 1: "Ch.11", "Ch.46", "Vol.04 Ch.019", "Ch.078.5"
    pattern1 = r'[Cc]h\.\s*(\d+\.?\d*)'
    match = re.search(pattern1, dirname)
    if match:
        return float(match.group(1))
    
    # Pattern 2: "Chapter 11", "Chapter 46"
    pattern2 = r'[Cc]hapter\s+(\d+\.?\d*)'
    match = re.search(pattern2, dirname)
    if match:
        return float(match.group(1))
    
    # Pattern 3: "Vol.01 Ch.003 - Network-Implants"
    pattern3 = r'[Vv]ol\.\d+\s*[Cc]h\.\s*(\d+\.?\d*)'
    match = re.search(pattern3, dirname)
    if match:
        return float(match.group(1))
    
    # Pattern 4: "Vol.5 Floor 41 The Swallowed-Up Voice"
    pattern4 = r'[Vv]ol\.\s*(\d+)\s*[Ff]loor\s+(\d+)'
    match = re.search(pattern4, dirname)
    if match:
        vol_num = int(match.group(1))
        floor_num = int(match.group(2))
        return float(f"{vol_num}{floor_num:03d}")  # e.g., Vol.5 Floor 41 becomes 5041
    
    # Pattern 5: "Vol.5 Extra In The Loft" - treat as chapter 0 of next volume
    pattern5 = r'[Vv]ol\.\s*(\d+)\s*[Ee]xtra'
    match = re.search(pattern5, dirname)
    if match:
        vol_num = int(match.group(1))
        return float(f"{vol_num + 1}000")  # e.g., Vol.5 Extra becomes 6000
    
    return None

def get_chapter_directories(manga_dir):
    """Get all chapter directories from the manga directory."""
    chapter_dirs = []
    for item in os.listdir(manga_dir):
        full_path = os.path.join(manga_dir, item)
        if os.path.isdir(full_path):
            chapter_dirs.append(item)
    
    # Sort chapters based on extracted chapter numbers
    # For special chapters (like Extra), they'll be sorted as 0 of the next volume
    return sorted(chapter_dirs, key=lambda x: extract_chapter_number(x) or float('inf'))

def process_chapter(chapter_dir, temp_dir, chapter_num_str):
    """Process all images in a chapter directory and copy them to a temporary directory with proper naming."""
    # Get all image files in the chapter directory
    image_files = [f for f in os.listdir(chapter_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    image_files.sort()  # Sort files to maintain order
    
    # Process each image file
    for i, image_file in enumerate(image_files, 1):
        # Get the file extension
        _, ext = os.path.splitext(image_file)
        
        # Create new filename with chapter prefix and page number
        new_name = f"{chapter_num_str}_{i:03d}{ext}"
        new_path = os.path.join(temp_dir, new_name)
        
        # Copy the file to the temporary directory with the new name
        shutil.copy2(os.path.join(chapter_dir, image_file), new_path)

def combine_chapters(manga_dir, output_path):
    """Combine all chapter directories into a single CBZ file."""
    chapter_dirs = get_chapter_directories(manga_dir)
    if not chapter_dirs:
        raise Exception("No chapter directories found in the selected manga directory")

    print(f"\nFound {len(chapter_dirs)} chapters to combine")
    
    # Create a temporary directory for processing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Process each chapter directory
        for chapter_dir_name in tqdm(chapter_dirs, desc="Processing chapters"):
            chapter_path = os.path.join(manga_dir, chapter_dir_name)
            chapter_num = extract_chapter_number(chapter_dir_name)
            
            if chapter_num is None:
                print(f"Warning: Could not extract chapter number from directory: {chapter_dir_name}")
                continue
            
            # Format chapter number with 4 digits (volume + chapter)
            chapter_num_str = f"{int(chapter_num):04d}"
            
            # Process the chapter
            process_chapter(chapter_path, temp_dir, chapter_num_str)
        
        # Create the output CBZ file
        with zipfile.ZipFile(output_path, 'w') as output_cbz:
            # Add all processed files to the CBZ
            for file in sorted(os.listdir(temp_dir)):
                file_path = os.path.join(temp_dir, file)
                output_cbz.write(file_path, file)

def main():
    # Set default source directory
    default_source_dir = r"C:\Users\Rhaz\Documents\Mangas"
    
    # Ask if user wants to use default path
    print(f"\nDefault manga directory: {default_source_dir}")
    use_default = input("Use default directory? (y/n) [y]: ").lower().strip()
    if not use_default:  # Empty input
        use_default = 'y'
    
    if use_default == 'y':
        source_dir = default_source_dir
    else:
        source_dir = input("Enter the source directory path (where manga directories are located): ").strip()
    
    if not os.path.exists(source_dir):
        raise Exception(f"Source directory '{source_dir}' does not exist")

    while True:
        try:
            # Get available manga directories
            manga_dirs = get_manga_directories(source_dir)
            
            # Let user select a manga
            selected_manga = select_manga(manga_dirs)
            manga_dir = os.path.join(source_dir, selected_manga)
            
            # Create output filename
            output_filename = f"{selected_manga}_combined.cbz"
            output_path = os.path.join(source_dir, output_filename)
            
            # Check if output file already exists
            if os.path.exists(output_path):
                while True:
                    choice = input(f"\nFile '{output_filename}' already exists. Overwrite? (y/n) [y]: ").lower().strip()
                    if not choice:  # Empty input
                        choice = 'y'
                    if choice in ['y', 'n']:
                        break
                    print("Please enter 'y' or 'n'")
                
                if choice == 'n':
                    print("\nSkipping this manga. Returning to selection...")
                    continue
            
            # Combine chapters
            print(f"\nCombining chapters for {selected_manga}...")
            combine_chapters(manga_dir, output_path)
            print(f"\nSuccessfully created combined CBZ file: {output_filename}")
            
            # Ask if user wants to process another manga
            while True:
                choice = input("\nDo you want to process another manga? (y/n) [y]: ").lower().strip()
                if not choice:  # Empty input
                    choice = 'y'
                if choice in ['y', 'n']:
                    break
                print("Please enter 'y' or 'n'")
            
            if choice == 'n':
                print("\nExiting program. Goodbye!")
                break

        except Exception as e:
            print(f"\nError: {str(e)}")
            # Ask if user wants to try again
            while True:
                choice = input("\nDo you want to try another manga? (y/n) [y]: ").lower().strip()
                if not choice:  # Empty input
                    choice = 'y'
                if choice in ['y', 'n']:
                    break
                print("Please enter 'y' or 'n'")
            
            if choice == 'n':
                print("\nExiting program. Goodbye!")
                break

if __name__ == "__main__":
    main()
