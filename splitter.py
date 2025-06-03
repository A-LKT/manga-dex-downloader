import os
import zipfile
import shutil
from pathlib import Path
import argparse
from typing import List, Tuple

def get_cbz_size(cbz_path: str) -> int:
    """Get the total size of all files in the CBZ archive."""
    total_size = 0
    with zipfile.ZipFile(cbz_path, 'r') as cbz:
        for file_info in cbz.infolist():
            total_size += file_info.file_size
    return total_size

def find_cbz_files(directory: str) -> List[str]:
    """Find all CBZ files in the given directory and its subdirectories."""
    cbz_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.cbz'):
                cbz_files.append(os.path.join(root, file))
    return cbz_files

def select_manga(cbz_files: List[str]) -> str:
    """Display an interactive menu to select a manga file."""
    if not cbz_files:
        print("No CBZ files found in the downloads directory!")
        return None

    print("\nAvailable manga files:")
    for i, file_path in enumerate(cbz_files, 1):
        size_gb = os.path.getsize(file_path) / (1024 * 1024 * 1024)
        print(f"{i}. {os.path.basename(file_path)} ({size_gb:.2f}GB)")

    while True:
        try:
            choice = int(input("\nSelect a manga to split (enter number): "))
            if 1 <= choice <= len(cbz_files):
                return cbz_files[choice - 1]
            print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a valid number.")

def split_cbz(input_path: str, output_dir: str, max_size: int = 3.5 * 1024 * 1024 * 1024) -> List[str]:
    """
    Split a large CBZ file into multiple smaller CBZ files.
    
    Args:
        input_path: Path to the input CBZ file
        output_dir: Directory to save the split CBZ files
        max_size: Maximum size for each split CBZ file in bytes (default: 3.5GB)
    
    Returns:
        List of paths to the created CBZ files
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Get the base name without extension
    base_name = Path(input_path).stem
    output_files = []
    
    with zipfile.ZipFile(input_path, 'r') as cbz:
        # Get all files in the CBZ
        files = cbz.namelist()
        files.sort()  # Sort to maintain chapter order
        
        current_part = 1
        current_size = 0
        current_files = []
        
        for file_name in files:
            file_info = cbz.getinfo(file_name)
            file_size = file_info.file_size
            
            # If adding this file would exceed the max size, create a new CBZ
            if current_size + file_size > max_size and current_files:
                # Create the current part
                output_path = os.path.join(output_dir, f"{base_name}_part{current_part}.cbz")
                with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as out_cbz:
                    for f in current_files:
                        out_cbz.writestr(f, cbz.read(f))
                output_files.append(output_path)
                
                # Reset for next part
                current_part += 1
                current_size = 0
                current_files = []
            
            current_files.append(file_name)
            current_size += file_size
        
        # Create the final part if there are remaining files
        if current_files:
            output_path = os.path.join(output_dir, f"{base_name}_part{current_part}.cbz")
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as out_cbz:
                for f in current_files:
                    out_cbz.writestr(f, cbz.read(f))
            output_files.append(output_path)
    
    return output_files

def main():
    parser = argparse.ArgumentParser(description='Split large CBZ files into smaller ones compatible with FAT32.')
    parser.add_argument('--output-dir', '-o', default='split_output',
                      help='Directory to save the split CBZ files (default: split_output)')
    parser.add_argument('--max-size', '-m', type=float, default=3.5,
                      help='Maximum size for each split CBZ file in GB (default: 3.5)')
    
    args = parser.parse_args()
    
    # Convert max size from GB to bytes
    max_size_bytes = int(args.max_size * 1024 * 1024 * 1024)
    
    # Find all CBZ files in the downloads directory
    downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
    cbz_files = find_cbz_files(downloads_dir)
    
    # Let user select a manga file
    selected_file = select_manga(cbz_files)
    if not selected_file:
        return
    
    # Get original file size
    original_size = get_cbz_size(selected_file)
    
    if original_size <= max_size_bytes:
        print(f"File is already smaller than {args.max_size}GB. No splitting needed.")
        return
    
    print(f"\nSplitting {os.path.basename(selected_file)} into parts...")
    output_files = split_cbz(selected_file, args.output_dir, max_size_bytes)
    
    print(f"\nSplit complete! Created {len(output_files)} files:")
    for file_path in output_files:
        size_gb = os.path.getsize(file_path) / (1024 * 1024 * 1024)
        print(f"- {os.path.basename(file_path)} ({size_gb:.2f}GB)")

if __name__ == '__main__':
    main()
