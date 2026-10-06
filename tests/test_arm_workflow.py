"""Check the manual ARM draft workflow without GitHub or a Proton build."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/arm64-draft.yml").read_text()


def job(name):
    return re.search(rf"^  {name}:\n(.*?)(?=^  \w+:|\Z)", WORKFLOW, re.M | re.S).group(1)


class ArmWorkflowTests(unittest.TestCase):
    def test_manual_native_arm_build(self):
        self.assertIn("  workflow_dispatch:", WORKFLOW)
        self.assertNotRegex(WORKFLOW.split("permissions:", 1)[0],
                            re.compile(r"^  (push|release):", re.M))
        build = job("build")
        self.assertIn("uses: ./.github/workflows/_job_build.yml", build)
        self.assertIn("runner: ubuntu-24.04-arm", build)
        self.assertIn("ref: ${{ needs.version.outputs.commit }}", build)
        self.assertIn("--target-arch=arm64", build)
        self.assertIn("-march=armv8.2-a", build)
        self.assertIn("-Ctarget-cpu=armv8.2-a", build)
        self.assertNotIn("nocona", build)
        for option in ("--without-tts", "--without-extras=all", "--without-vklayers=all",
                       "--without-nvidia-libs"):
            self.assertIn(option, build)

    def test_matching_artifacts_and_separate_draft(self):
        for name in ("build", "upload"):
            self.assertIn("name: ${{ needs.version.outputs.name }}", job(name))
        self.assertIn("needs: [version, release]", job("upload"))
        self.assertIn("uses: ./.github/workflows/_job_upload.yml", job("upload"))
        self.assertIn("version: ${{ needs.version.outputs.draft_version }}", job("upload"))
        self.assertIn('name=proton-$VERSION-arm64', job("version"))
        self.assertIn('draft_version=$VERSION-arm64-draft', job("version"))
        self.assertNotIn("arm64", (ROOT / ".github/workflows/release.yml").read_text())

    def test_reusable_build_checks_out_requested_ref(self):
        source = (ROOT / ".github/workflows/_job_build.yml").read_text()
        self.assertRegex(source, r"ref:\n\s+required: false\n\s+type: string\n\s+default: ''")
        self.assertIn("ref: ${{ inputs.ref }}", source)

    def release(self, existing):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            gh = directory / "gh"
            gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n'
                          'if [ "$2" = view ]; then\n'
                          '  [ "$EXISTING" != missing ] || exit 1\n'
                          '  echo "$EXISTING"\nfi\n')
            gh.chmod(0o755)
            environment = os.environ.copy()
            environment.update(PATH=f"{directory}:{environment['PATH']}",
                               CALLS=str(directory / "calls"), EXISTING=existing,
                               VERSION="fixture-arm64-draft", COMMIT="abcdef")
            script = textwrap.dedent(job("release").split("        run: |\n", 1)[1])
            result = subprocess.run(["bash", "-eu", "-c", script], env=environment,
                                    capture_output=True, text=True, timeout=30)
            return result, (directory / "calls").read_text()

    def test_new_release_stays_draft(self):
        result, calls = self.release("missing")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release create fixture-arm64-draft --draft --prerelease --target abcdef", calls)

    def test_existing_draft_can_be_updated(self):
        result, calls = self.release("true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("release create", calls)

    def test_published_release_is_rejected(self):
        result, calls = self.release("false")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to upload", result.stderr)
        self.assertNotIn("release create", calls)


if __name__ == "__main__":
    unittest.main()
