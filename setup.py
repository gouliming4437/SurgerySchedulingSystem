import os
import shutil

def setup_project():
    # Get the base directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create directories
    directories = [
        os.path.join(base_dir, 'templates'),
        os.path.join(base_dir, 'static', 'css'),
        os.path.join(base_dir, 'backups')
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"Created directory: {directory}")

if __name__ == "__main__":
    setup_project() 