"""Where the gallery is put on the web, and where it is not.

The deploy job of publish.yml is the only thing that puts the gallery on
the web, and the address it lands on is a wall of the box every stack
plays in (docs/MAINTAINING.md, "Where the gallery may live"). These tests
read the workflow as text, with the standard library alone, and fail if
the job could deploy from anywhere but the oxt-stacks organization.
"""

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))

OWNER = 'oxt-stacks'
GALLERY = 'https://oxt-stacks.github.io/oxt-community-stacks/'


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


def job(workflow, name):
    """The text of one job of a workflow: from its key to the next job."""
    m = re.search(r'^  %s:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)' % re.escape(name),
                  workflow, re.M | re.S)
    if not m:
        raise AssertionError('no job %r' % name)
    return m.group(1)


class WhereItLives(unittest.TestCase):
    def setUp(self):
        self.publish = read('.github', 'workflows', 'publish.yml')

    def test_only_the_deploy_job_writes_pages(self):
        self.assertEqual(self.publish.count('pages: write'), 1)
        self.assertIn('pages: write', job(self.publish, 'deploy'))

    def test_the_deploy_job_runs_only_for_the_gallerys_own_organization(self):
        ifs = re.findall(r'^    if: (.*)$', job(self.publish, 'deploy'), re.M)
        # One condition, naming the owner it MAY run for: a "not this
        # owner" test would deploy from every fork and every new home.
        self.assertEqual(ifs, ["github.repository_owner == '%s'" % OWNER])

    def test_the_live_check_follows_the_deploy(self):
        self.assertIn('needs: deploy', job(self.publish, 'live'))

    def test_pages_link_to_the_repository_where_it_lives(self):
        saved = os.environ.pop('GITHUB_REPOSITORY', None)
        try:
            import importlib
            import build_site
            importlib.reload(build_site)
            self.assertEqual(build_site.REPOSITORY_URL,
                             'https://github.com/%s/oxt-community-stacks' % OWNER)
        finally:
            if saved is not None:
                os.environ['GITHUB_REPOSITORY'] = saved

    def test_the_docs_give_the_gallerys_address(self):
        self.assertIn(GALLERY, read('README.md'))
        self.assertIn(GALLERY, read('docs', 'MAINTAINING.md'))


if __name__ == '__main__':
    unittest.main()
