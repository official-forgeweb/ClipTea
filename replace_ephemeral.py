import os
import glob

cogs_dir = r"c:\Users\lenovo\OneDrive\Desktop\Projects\ClipTea\cogs"
files = glob.glob(os.path.join(cogs_dir, "*.py"))

for file_path in files:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Change ephemeral=False back to ephemeral=True per user's request
    if "ephemeral=False" in content:
        content = content.replace("ephemeral=False", "ephemeral=True")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {file_path}")
