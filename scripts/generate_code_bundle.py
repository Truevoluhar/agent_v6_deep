from __future__ import annotations

from pathlib import Path
import zipfile


FILES: list[tuple[str, str]] = [
    ("python/app.py", "def greet(name: str) -> str:\n    return f'Hello, {name}!'\n\n\nif __name__ == '__main__':\n    print(greet('world'))\n"),
    ("python/math_utils.py", "def fib(n: int) -> int:\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"),
    ("python/file_report.py", "from pathlib import Path\n\n\ndef count_lines(path: str) -> int:\n    return len(Path(path).read_text(encoding='utf-8').splitlines())\n"),
    ("javascript/index.js", "function sum(values) {\n  return values.reduce((total, value) => total + value, 0);\n}\n\nconsole.log(sum([1, 2, 3, 4]));\n"),
    ("javascript/server.js", "const http = require('http');\n\nhttp.createServer((req, res) => {\n  res.end('ok');\n}).listen(3000);\n"),
    ("typescript/user.ts", "export interface User {\n  id: string;\n  name: string;\n}\n\nexport const formatUser = (user: User): string => `${user.id}:${user.name}`;\n"),
    ("typescript/config.ts", "type Config = { retries: number; verbose: boolean };\n\nexport const defaultConfig: Config = { retries: 3, verbose: false };\n"),
    ("go/main.go", "package main\n\nimport \"fmt\"\n\nfunc main() {\n    fmt.Println(\"hello from go\")\n}\n"),
    ("go/http_client.go", "package main\n\nimport (\n    \"fmt\"\n    \"net/http\"\n)\n\nfunc status(url string) string {\n    res, _ := http.Get(url)\n    return fmt.Sprintf(\"%d\", res.StatusCode)\n}\n"),
    ("rust/main.rs", "fn main() {\n    println!(\"hello from rust\");\n}\n"),
    ("rust/lib.rs", "pub fn is_even(value: i32) -> bool {\n    value % 2 == 0\n}\n"),
    ("java/App.java", "public class App {\n    public static void main(String[] args) {\n        System.out.println(\"Hello Java\");\n    }\n}\n"),
    ("java/Calculator.java", "public class Calculator {\n    public int add(int a, int b) {\n        return a + b;\n    }\n}\n"),
    ("c/main.c", "#include <stdio.h>\n\nint main(void) {\n    printf(\"hello c\\n\");\n    return 0;\n}\n"),
    ("cpp/vector_sum.cpp", "#include <iostream>\n#include <vector>\n\nint main() {\n    std::vector<int> values{1, 2, 3};\n    int sum = 0;\n    for (int value : values) sum += value;\n    std::cout << sum << std::endl;\n}\n"),
    ("csharp/Program.cs", "using System;\n\nConsole.WriteLine(\"Hello C#\");\n"),
    ("ruby/app.rb", "def titleize(text)\n  text.split.map(&:capitalize).join(' ')\nend\n\nputs titleize('ruby sample app')\n"),
    ("php/index.php", "<?php\nfunction square(int $value): int {\n    return $value * $value;\n}\n\necho square(9);\n"),
    ("swift/main.swift", "import Foundation\n\nprint(\"hello swift\")\n"),
    ("kotlin/Main.kt", "fun main() {\n    println(\"hello kotlin\")\n}\n"),
    ("scala/Main.scala", "object Main extends App {\n  println(\"hello scala\")\n}\n"),
    ("bash/deploy.sh", "#!/usr/bin/env bash\nset -euo pipefail\n\necho \"deploying application\"\n"),
    ("powershell/cleanup.ps1", "param([string]$Path = '.')\nGet-ChildItem -Path $Path -File | Remove-Item -WhatIf\n"),
    ("sql/schema.sql", "create table users (\n  id integer primary key,\n  email text not null unique,\n  created_at text not null\n);\n"),
    ("html/index.html", "<!doctype html>\n<html>\n  <body>\n    <h1>Sample Site</h1>\n  </body>\n</html>\n"),
    ("css/styles.css", "body {\n  font-family: sans-serif;\n  margin: 2rem;\n}\n"),
    ("json/settings.json", "{\n  \"appName\": \"bundle-sample\",\n  \"enabled\": true,\n  \"retries\": 2\n}\n"),
    ("yaml/pipeline.yaml", "steps:\n  - name: install\n    run: npm ci\n  - name: test\n    run: npm test\n"),
    ("docker/Dockerfile", "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nCMD [\"python\", \"app.py\"]\n"),
    ("terraform/main.tf", "terraform {\n  required_version = \">= 1.6.0\"\n}\n\nresource \"null_resource\" \"example\" {}\n"),
]


def main() -> None:
    workspace_root = Path("/workspaces/agent_v6_deep/data/agent_workspace")
    source_root = workspace_root / "uploads" / "code_bundle_30"
    zip_path = workspace_root / "uploads" / "code_bundle_30.zip"
    target_root = workspace_root / "analysis" / "code_bundle_30_readmes"
    task_path = workspace_root / "analysis" / "code_bundle_30_task.md"

    source_root.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)

    for relative_path, content in FILES:
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_root))

    task_path.write_text(
        "\n".join(
            [
                "# Code Bundle Task",
                "",
                "Input zip: `/uploads/code_bundle_30.zip`",
                "Expanded source tree: `/uploads/code_bundle_30/`",
                "Desired output root: `/analysis/code_bundle_30_readmes/`",
                "",
                "For each code file in the bundle, create a sibling `README.md` in the output root",
                "that explains the file purpose, language, main functions/classes, inputs/outputs,",
                "and any noteworthy implementation details.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Created {len(FILES)} code files at {source_root}")
    print(f"Created zip at {zip_path}")
    print(f"Prepared output directory at {target_root}")


if __name__ == "__main__":
    main()
