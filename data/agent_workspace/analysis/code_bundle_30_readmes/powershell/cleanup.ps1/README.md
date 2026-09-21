# cleanup.ps1

- **Source file:** `/uploads/code_bundle_30/powershell/cleanup.ps1`
- **Language:** PowerShell
- **Purpose:** Previews removal of files in a target directory.
- **Key functions/classes:** Script parameter `Path`; pipeline `Get-ChildItem ... | Remove-Item -WhatIf`.
- **Inputs:** Optional `-Path` string parameter defaulting to `.`.
- **Outputs:** Emits PowerShell `-WhatIf` messages describing which files would be removed.
- **Notable implementation details:** Filters to files with `-File`; `Remove-Item -WhatIf` prevents actual deletion, making the script a dry run by default.
