from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SiteNavUiTests(unittest.TestCase):
    def test_mount_keeps_butler_visible_and_preserves_all_other_tools_under_more(self) -> None:
        script = r"""
        const fs = require('fs');
        const vm = require('vm');
        class Element {
          constructor(tag) {
            this.tagName = tag.toUpperCase();
            this.children = [];
            this.attributes = {};
            this.dataset = {};
            this.className = '';
            this.textContent = '';
            this.open = false;
            this.classList = { add: (...names) => { this.className += ' ' + names.join(' '); } };
          }
          appendChild(child) { this.children.push(child); return child; }
          setAttribute(name, value) { this.attributes[name] = value; }
          get innerHTML() { return ''; }
          set innerHTML(_value) { this.children = []; }
        }
        const document = {
          readyState: 'loading',
          addEventListener() {},
          removeEventListener() {},
          createElement: (tag) => new Element(tag),
          getElementById: () => null,
        };
        const window = { location: { pathname: '/settings' } };
        vm.runInNewContext(fs.readFileSync('web/shared/site-nav.js', 'utf8'), { window, document });
        const host = new Element('div');
        window.SiteNav.mount(host);
        const directLinks = host.children.filter((child) => child.tagName === 'A');
        const more = host.children.find((child) => child.tagName === 'DETAILS');
        const summary = more && more.children.find((child) => child.tagName === 'SUMMARY');
        const menu = more && more.children.find((child) => child.className === 'nav-more-menu');
        const secondaryLinks = menu ? menu.children.filter((child) => child.tagName === 'A') : [];
        const activeSecondary = secondaryLinks.find((child) => child.attributes['aria-current'] === 'page');
        window.location.pathname = '/butler';
        const butlerHost = new Element('nav');
        window.SiteNav.mount(butlerHost);
        const butlerDirectLinks = butlerHost.children.filter((child) => child.tagName === 'A');
        const activeButler = butlerDirectLinks.find((child) => child.attributes['aria-current'] === 'page');
        const butlerMore = butlerHost.children.find((child) => child.tagName === 'DETAILS');
        const butlerSummary = butlerMore && butlerMore.children.find((child) => child.tagName === 'SUMMARY');
        console.log(JSON.stringify({
          directCount: directLinks.length,
          directIds: directLinks.map((item) => item.dataset.navId),
          moreText: summary && summary.textContent,
          secondaryCount: secondaryLinks.length,
          secondaryIds: secondaryLinks.map((item) => item.dataset.navId),
          moreOpen: more && more.open,
          moreActive: summary && summary.className.includes('active'),
          moreExpanded: summary && summary.attributes['aria-expanded'],
          navRole: host.attributes.role,
          navLabel: host.attributes['aria-label'],
          menuRole: menu && menu.attributes.role,
          activeSecondary: activeSecondary && activeSecondary.dataset.navId,
          activeButler: activeButler && activeButler.dataset.navId,
          butlerMoreActive: butlerSummary && butlerSummary.className.includes('active'),
          butlerHostRole: butlerHost.attributes.role || null,
        }));
        """
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["directCount"], 8)
        self.assertEqual(
            data["directIds"],
            [
                "gallery",
                "generated",
                "studio",
                "butler",
                "remix",
                "progress",
                "nai-tags",
                "pixiv",
            ],
        )
        self.assertTrue(data["moreText"].startswith("更多"))
        self.assertEqual(data["secondaryCount"], 12)  # + 经典图库 + codex + 合规
        self.assertNotIn("butler", data["secondaryIds"])
        for nav_id in ("queue", "director", "references", "favorites", "classic"):
            with self.subTest(nav_id=nav_id):
                self.assertIn(nav_id, data["secondaryIds"])
        self.assertFalse(data["moreOpen"], "secondary-page navigation must not cover page content by default")
        self.assertTrue(data["moreActive"], "More should still indicate the active secondary page")
        self.assertEqual(data["moreExpanded"], "false")
        self.assertEqual(data["navRole"], "navigation")
        self.assertEqual(data["navLabel"], "主导航")
        self.assertEqual(data["menuRole"], "group")
        self.assertEqual(data["activeSecondary"], "settings")
        self.assertEqual(data["activeButler"], "butler")
        self.assertFalse(data["butlerMoreActive"])
        self.assertIsNone(data["butlerHostRole"], "native nav elements must not receive a redundant role")


if __name__ == "__main__":
    unittest.main()
