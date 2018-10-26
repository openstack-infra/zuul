import gzip
import os
import re
import yaml


def get_log_age(path):
    filename = os.path.basename(path)
    parts = filename.split('.')
    if len(parts) < 4:
        return 0
    else:
        return int(parts[2])


class LogScraper(object):
    # Example log line
    # 2018-10-26 16:14:47,527 INFO zuul.nodepool: Nodeset <NodeSet two-centos-7-nodes [<Node 0000058431 ('primary',):centos-7>, <Node 0000058468 ('secondary',):centos-7>]> with 2 nodes was in use for 6241.08082151413 seconds for build <Build 530c4ca7af9e44dcb535e7074258e803 of tripleo-ci-centos-7-scenario008-multinode-oooq-container voting:False on <Worker ze05.openstack.org>> for project openstack/tripleo-quickstart-extras  # noqa
    r = re.compile(r'(?P<timestamp>\d+-\d+-\d+ \d\d:\d\d:\d\d,\d\d\d) INFO zuul.nodepool: Nodeset <.*> with (?P<nodes>\d+) nodes was in use for (?P<secs>\d+(.[\d\-e]+)?) seconds for build <Build \w+ of (?P<job>[^\s]+) voting:\w+ on .* for project (?P<repos>[^\s]+)')  # noqa

    def __init__(self):
        self.repos = {}
        self.sorted_repos = []
        self.jobs = {}
        self.sorted_jobs = []
        self.total_usage = 0.0
        self.projects = {}
        self.sorted_projects = []
        self.start_time = None
        self.end_time = None

    def scrape_file(self, fn):
        if fn.endswith('.gz'):
            open_f = gzip.open
        else:
            open_f = open
        with open_f(fn, 'rt') as f:
            for line in f:
                if 'nodes was in use for' in line:
                    m = self.r.match(line)
                    if not m:
                        continue
                    g = m.groupdict()
                    repo = g['repos']
                    secs = float(g['secs'])
                    nodes = int(g['nodes'])
                    job = g['job']
                    if not self.start_time:
                        self.start_time = g['timestamp']
                    self.end_time = g['timestamp']
                    if repo not in self.repos:
                        self.repos[repo] = {}
                        self.repos[repo]['total'] = 0.0
                    node_time = nodes * secs
                    self.total_usage += node_time
                    self.repos[repo]['total'] += node_time
                    if job not in self.jobs:
                        self.jobs[job] = 0.0
                    if job not in self.repos[repo]:
                        self.repos[repo][job] = 0.0
                    self.jobs[job] += node_time
                    self.repos[repo][job] += node_time

    def list_log_files(self, path='/var/log/zuul'):
        ret = []
        entries = os.listdir(path)
        prefix = os.path.join(path, 'zuul.log')
        for entry in entries:
            entry = os.path.join(path, entry)
            if os.path.isfile(entry) and entry.startswith(prefix):
                ret.append(entry)
        ret.sort(key=get_log_age, reverse=True)
        return ret

    def sort_repos(self):
        for repo in self.repos:
            self.sorted_repos.append((repo, self.repos[repo]['total']))

        self.sorted_repos.sort(key=lambda x: x[1], reverse=True)

    def sort_jobs(self):
        for job, usage in self.jobs.items():
            self.sorted_jobs.append((job, usage))

        self.sorted_jobs.sort(key=lambda x: x[1], reverse=True)

    def calculate_project_usage(self):
        '''Group usage by logical project/effort

        It is often the case that a single repo doesn't capture the work
        of a logical project or effort. If this is the case in your situation
        you can create a projects.yaml file that groups together repos
        under logical project names to report usage by that logical grouping.

        The projects.yaml should be in your current directory and have this
        format:

          project_name:
            deliverables:
              logical_deliverable_name:
                repos:
                  - repo1
                  - repo2

          project_name2:
            deliverables:
              logical_deliverable_name2:
                repos:
                  - repo3
                  - repo4
        '''
        if not os.path.exists('projects.yaml'):
            return self.sorted_projects
        with open('projects.yaml') as f:
            y = yaml.load(f)
        for name, v in y.items():
            self.projects[name] = 0.0
            for deliverable in v['deliverables'].values():
                for repo in deliverable['repos']:
                    if repo in self.repos:
                        self.projects[name] += self.repos[repo]['total']

        for project, usage in self.projects.items():
            self.sorted_projects.append((project, usage))

        self.sorted_projects.sort(key=lambda x: x[1], reverse=True)


scraper = LogScraper()
for fn in scraper.list_log_files():
    scraper.scrape_file(fn)

print('For period from %s to %s' % (scraper.start_time, scraper.end_time))
print('Total node time used: %.2fs' % scraper.total_usage)
print()

scraper.calculate_project_usage()
if scraper.sorted_projects:
    print('Top 20 logical projects by resource usage:')
    for project, total in scraper.sorted_projects[:20]:
        percentage = (total / scraper.total_usage) * 100
        print('%s: %.2fs, %.2f%%' % (project, total, percentage))
    print()

scraper.sort_repos()
print('Top 20 repos by resource usage:')
for repo, total in scraper.sorted_repos[:20]:
    percentage = (total / scraper.total_usage) * 100
    print('%s: %.2fs, %.2f%%' % (repo, total, percentage))
print()

scraper.sort_jobs()
print('Top 20 jobs by resource usage:')
for job, total in scraper.sorted_jobs[:20]:
    percentage = (total / scraper.total_usage) * 100
    print('%s: %.2fs, %.2f%%' % (job, total, percentage))
print()
