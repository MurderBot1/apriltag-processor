"""Publish a markdown report from a CI job: append to the job summary ($GITHUB_STEP_SUMMARY) and create-or-update ONE pull-request comment
identified by a hidden marker.  Standard library only.

    python tools/ci_report.py --marker category-normal --body-file results/ci/normal.md

On pull_request runs from forks (and on any run where the token cannot write comments) GITHUB_TOKEN is read-only: the comment is skipped
with a notice and the job summary still carries the report -- the job never fails because of the comment.
Needs env GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_EVENT_PATH (all set by Actions); the job needs `permissions: pull-requests: write`."""
import os, sys, json, argparse, urllib.request, urllib.error


def api(method, url, token, data=None):
    req = urllib.request.Request(url, method=method, data=None if data is None else json.dumps(data).encode(),
                                 headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                                          'Content-Type': 'application/json', 'User-Agent': 'ci-report'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b'null'), r.headers


def find_comment(base, token, tag):
    url = f'{base}?per_page=100'
    while url:
        items, hdr = api('GET', url, token)
        for c in items:
            if tag in (c.get('body') or ''):
                return c['id']
        url = None
        for part in (hdr.get('Link') or '').split(','):
            if 'rel="next"' in part:
                url = part.split(';')[0].strip(' <>')
    return None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--marker', required=True); ap.add_argument('--body-file', required=True)
    a = ap.parse_args()
    body = open(a.body_file, encoding='utf-8').read()
    summ = os.environ.get('GITHUB_STEP_SUMMARY')
    if summ:
        open(summ, 'a', encoding='utf-8').write(body + '\n')
    print(body)
    ev_path = os.environ.get('GITHUB_EVENT_PATH'); token = os.environ.get('GITHUB_TOKEN'); repo = os.environ.get('GITHUB_REPOSITORY')
    ev = json.load(open(ev_path)) if ev_path and os.path.exists(ev_path) else {}
    pr = ev.get('pull_request') or {}
    if not (pr.get('number') and token and repo):
        print('::notice::not a pull_request run (or no token): job summary only, no PR comment'); return
    if (pr.get('head', {}).get('repo', {}).get('full_name') or repo) != repo:
        print('::notice::pull request from a fork: GITHUB_TOKEN is read-only, PR comment skipped (result is in the job summary)'); return
    tag = f'<!-- ci-report:{a.marker} -->'
    text = tag + '\n' + body
    base = f"https://api.github.com/repos/{repo}/issues/{pr['number']}/comments"
    try:
        cid = find_comment(base, token, tag)
        if cid:
            api('PATCH', f'https://api.github.com/repos/{repo}/issues/comments/{cid}', token, {'body': text}); print('updated comment', cid)
        else:
            api('POST', base, token, {'body': text}); print('created comment')
    except urllib.error.HTTPError as e:
        print(f'::warning::could not write the PR comment (HTTP {e.code}: {e.reason}); the result is in the job summary')


if __name__ == '__main__':
    main()
