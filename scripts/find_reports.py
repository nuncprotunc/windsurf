import sys
from pathlib import Path

def main():
    # Check script location
    script_dir = Path(__file__).resolve().parent
    print(f"Script directory: {script_dir}")
    
    # Check for reports directory in various locations
    possible_paths = [
        script_dir / 'reports',
        script_dir.parent / 'reports',
        Path('D:/Dropbox/Windsurf/reports'),
        Path('D:/Dropbox/Windsurf/scripts/reports')
    ]
    
    for path in possible_paths:
        print(f"\nChecking: {path}")
        if path.exists():
            print(f"  Exists! Contents:")
            try:
                for item in path.rglob('*'):
                    print(f"  - {item.relative_to(path.parent)}")
            except Exception as e:
                print(f"  Error listing contents: {e}")
        else:
            print("  Does not exist")

if __name__ == "__main__":
    main()
