import os

# The root directory of the project
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# File extensions to count
FILE_EXTENSIONS = {'.py', '.html', '.js', '.css'}

# Directories to ignore
IGNORE_DIRS = {
    '.git',
    '__pycache__',
    'node_modules',
    'migrations',
    'media',
    'logs',
    '.idea',
    'certs'
}

def count_lines_in_file(file_path):
    """Counts the number of lines in a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return len(f.readlines())
    except Exception:
        # Ignore files that can't be opened or read (e.g., binary files)
        return 0

def main():
    """
    Main function to walk through the directory and count lines of code.
    """
    line_counts = {ext: 0 for ext in FILE_EXTENSIONS}
    file_counts = {ext: 0 for ext in FILE_EXTENSIONS}
    total_lines = 0
    total_files = 0

    

    for root, dirs, files in os.walk(ROOT_DIR):
        # Remove ignored directories from the walk
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in FILE_EXTENSIONS:
                file_path = os.path.join(root, file)
                lines = count_lines_in_file(file_path)
                if lines > 0:
                    line_counts[ext] += lines
                    file_counts[ext] += 1
                    total_lines += lines
                    total_files += 1

    # Print the results
    

if __name__ == "__main__":
    main()
