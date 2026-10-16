"""A entrada aposentada encerra sem ferramentas externas em todos os modos antigos."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "acompanhar.sh"


class AcompanharScriptTest(unittest.TestCase):
    def test_modos_aposentados_nao_chamam_ferramentas(self):
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        for argumentos in ((), ("atualizar",), ("offline",), ("verificar",), ("servir",), ("mod",), ("executar",)):
            for ferramentas_presentes in (True, False):
                with self.subTest(argumentos=argumentos, ferramentas_presentes=ferramentas_presentes):
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        script = root / "acompanhar.sh"
                        shutil.copyfile(SCRIPT, script)
                        ferramentas = root / "bin"
                        ferramentas.mkdir()
                        chamadas = root / "chamadas"
                        if ferramentas_presentes:
                            for nome in ("dirname", "python3", "claude", "gh", "git", "curl", "wget"):
                                ferramenta = ferramentas / nome
                                ferramenta.write_text(
                                    f'#!{bash}\nprintf "%s\\n" "$0" >> "$CALL_TRACE"\nexit 97\n'
                                )
                                ferramenta.chmod(0o755)
                        resultado = subprocess.run(
                            [bash, "--noprofile", "--norc", str(script), *argumentos],
                            cwd=root,
                            env={"PATH": str(ferramentas), "CALL_TRACE": str(chamadas)},
                            capture_output=True,
                            text=True,
                            timeout=5,
                            check=False,
                        )
                        self.assertFalse(chamadas.exists(), "uma ferramenta externa foi chamada")
                        self.assertEqual(resultado.returncode, 0, resultado.stderr)
                        self.assertIn("ROADMAP.md", resultado.stdout)
                        self.assertIn("aposentado", resultado.stdout.lower())
                        self.assertEqual(resultado.stderr, "")
                        self.assertEqual(set(root.iterdir()), {script, ferramentas})
