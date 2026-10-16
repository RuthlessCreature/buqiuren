"""Regression coverage for the read-only internal dossier interface."""
from __future__ import annotations

import shutil
import subprocess
import textwrap

import pytest

from admin_ui import ADMIN_HTML


def _javascript() -> str:
    return ADMIN_HTML.split("<script>", 1)[1].split("</script>", 1)[0]


def test_admin_dossier_has_structured_read_only_panels():
    for label in ("对话卷宗", "个人档案", "附件索引", "审计记录", "原始数据"):
        assert label in ADMIN_HTML
    assert '/api/admin/users' in ADMIN_HTML
    assert '/api/admin/user?id=' in ADMIN_HTML
    assert "展开本轮推演过程" in ADMIN_HTML
    assert "messageSearch" in ADMIN_HTML
    assert "roleFilter" in ADMIN_HTML
    assert 'JSON.stringify(d,null,2)' not in ADMIN_HTML
    assert "deleteUser" not in ADMIN_HTML
    assert "<script src=" not in ADMIN_HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_admin_javascript_syntax_and_safe_markdown(tmp_path):
    script = _javascript()
    script_path = tmp_path / "admin.js"
    script_path.write_text(script, encoding="utf-8")
    subprocess.run(["node", "--check", str(script_path)], check=True, capture_output=True, text=True)

    runner = textwrap.dedent(r"""
      const fs = require('fs');
      const vm = require('vm');
      const source = fs.readFileSync(process.argv[1], 'utf8');
      const bootstrap = source.replace(
        'loadUsers();\n})();',
        'globalThis.__unitTest={markdown,safe,fmtJSON};\n})();'
      );
      if (bootstrap === source) throw Error('Could not expose pure render functions');
      const fake = {
        document: {
          getElementById: () => ({addEventListener(){}}),
          addEventListener(){}
        },
        console
      };
      fake.globalThis = fake;
      vm.runInNewContext(bootstrap, fake);
      const render = fake.__unitTest.markdown;
      const tick = String.fromCharCode(96);
      const html = render('## 盘骨\n\n**关节**与 '+tick+'日柱'+tick+'\n\n| 年 | 运 |\n| --- | --- |\n| 2026 | 丙午 |');
      if (!html.includes('<h2>盘骨</h2>')) throw Error('Markdown heading missing');
      if (!html.includes('<strong>关节</strong>')) throw Error('Markdown strong missing');
      if (!html.includes('<code>日柱</code>')) throw Error('Markdown inline code missing');
      if (!html.includes('<table>')) throw Error('Markdown table missing');
      const hostile = render('<img src=x onerror=alert(1)>\n\n[bad](javascript:alert(1))');
      if (hostile.includes('<img')) throw Error('HTML was not escaped');
      if (hostile.includes('href="javascript:')) throw Error('Dangerous URL rendered');
      if (!hostile.includes('&lt;img')) throw Error('Expected escaped HTML');
    """)
    subprocess.run(["node", "-e", runner, str(script_path)], check=True, capture_output=True, text=True)
