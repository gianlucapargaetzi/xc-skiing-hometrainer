import os

def list_files(directory, extension=None):
    """
    Returns a list of filenames in the specified directory, optionally filtered by file extension.
    
    Args:
        directory (str): The path to the directory.
        extension (str, optional): The file extension to filter by (e.g., '.gpx'). Defaults to None.
        
    Returns:
        list of str: Filenames in the directory filtered by the specified extension, or all files if none is provided.
    """
    # try:
    # List all items in the directory
    all_items = os.listdir(directory)
    # Filter out directories
    files_only = [item for item in all_items if os.path.isfile(os.path.join(directory, item))]
    
    # If an extension is provided, filter by it
    if extension:
        return [file for file in files_only if file.endswith(extension)]
    else:
        # Return all files if no extension is provided
        return files_only
    # except FileNotFoundError:
    #     print(f"The directory '{directory}' does not exist.")
    #     return []
    # except PermissionError:
    #     print(f"Permission denied to access the directory '{directory}'.")
    #     return []
