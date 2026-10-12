"""Recover only original, missing Omneum 1.0.3 distributions; never rebuild."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

REPO = 'cole-h06/omneum'
RUN = 38296556128
ARTIFACT = 11769345475
COMMIT = 'dc22a0db7ba429e9fcfe97f33016ed30b90403e9'
TAG_OBJECT = '256058c10be677983adc4a94009a90c93f4a80c5'
ZIP_SHA256 = 'c03e72cdaf9dd02c9b773f3982bb4937eb3de01fce5b302cf0204e765e59e3b5'
EXPECTED = {'omneum-1.0.3-cp311-cp311-macosx_10_12_x86_64.whl': '84974b3b7572343739cb4c302662c77a102daa302ff20a42051f7baf7a0dfa87', 'omneum-1.0.3-cp311-cp311-macosx_11_0_arm64.whl': '559712fbc6310df6103a6cf79887c54164a3edc48d33c2e752943b2f6b66b0bf', 'omneum-1.0.3-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl': '9d7c5c12963d3c31cb3f3e647133befe687e5f67131f9cc484f59c9e401b6bc2', 'omneum-1.0.3-cp311-cp311-win_amd64.whl': '39d5a284ba3cc34e54a3d2e96e52fed241e8d6916942b74c6354df2248407c4d', 'omneum-1.0.3-cp312-cp312-macosx_10_12_x86_64.whl': 'cf266da7d8737734b525767af358820d9ac8b218c4a05038dc71e9f97f83ffb7', 'omneum-1.0.3-cp312-cp312-macosx_11_0_arm64.whl': 'ea7c497500b1093dfa2e1ffc2a6afa2b4e4c784891f131e7e909e267742661e6', 'omneum-1.0.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl': '4cea3ccc5b5b0bfe553ebfd430b568df63cc78f0908a8264926d38fc6956c673', 'omneum-1.0.3-cp312-cp312-win_amd64.whl': '13f7a48d2db717ecc0f04f5b896d9896dd11f1453de8ad358fd22d1e3909d1bc', 'omneum-1.0.3-cp313-cp313-macosx_10_12_x86_64.whl': '494ac0ae435fed03840f233c4abfdaeb0e7bbab12ba6f6fc89fe18ab81ea37cc', 'omneum-1.0.3-cp313-cp313-macosx_11_0_arm64.whl': '0693efcfab740cd9a871d299d7e2772a445ce08b2c2f39857578ba1a014f4421', 'omneum-1.0.3-cp313-cp313-manylinux_2_17_x86_64.manylinux2014_x86_64.whl': '4231046846f595eb81742ad968889fa9aa615d9ff4afa4f47f1067e9b52a7d57', 'omneum-1.0.3-cp313-cp313-win_amd64.whl': '3b7eded811b07cc691c945d2a5f55556751137ff6c9196e78d3fd70c20574622', 'omneum-1.0.3-cp314-cp314-macosx_10_12_x86_64.whl': 'bd35cd5768eb6cd175be55d2b46dc9e699b0ce16a1fb389750e3b29e2b410a6b', 'omneum-1.0.3-cp314-cp314-macosx_11_0_arm64.whl': '435050e897c272554489b9744614313afcf9da8f011f1b6ea0888eb4f782fd90', 'omneum-1.0.3-cp314-cp314-manylinux_2_17_x86_64.manylinux2014_x86_64.whl': '6c78693498c9a3730577a86f80c0bd67a39803765681d0336fb17a0990695832', 'omneum-1.0.3-cp314-cp314-win_amd64.whl': '47b03e924b7229208e61bba8567ee381feadf230ee22ecafe60a9f8b53c30b7e', 'omneum-1.0.3.tar.gz': '7fe877195554dfe53b3281349379507050183fddebf687b93ef7467cb0190b3d'}
ALLOWED_MISSING = frozenset(['omneum-1.0.3-cp314-cp314-macosx_11_0_arm64.whl', 'omneum-1.0.3-cp314-cp314-manylinux_2_17_x86_64.manylinux2014_x86_64.whl', 'omneum-1.0.3-cp314-cp314-win_amd64.whl', 'omneum-1.0.3.tar.gz'])


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def gh(path):
    return json.loads(subprocess.check_output(['gh', 'api', 'repos/'+REPO+'/'+path], text=True))


def verify_origin():
    run = gh('actions/runs/'+str(RUN))
    require(run['head_sha'] == COMMIT and run['head_branch'] == 'v1.0.3'
            and run['event'] == 'push' and run['status'] == 'completed'
            and run['run_attempt'] == 1, 'original release run identity changed')
    jobs = gh('actions/runs/'+str(RUN)+'/jobs?per_page=100')
    require(jobs['total_count'] == len(jobs['jobs']) == 45, 'original release job inventory incomplete')
    for job in jobs['jobs']:
        require(job['head_sha'] == COMMIT, 'original job revision mismatch')
        if job['name'] != 'Publish validated wheels to PyPI':
            require(job['conclusion'] == 'success', 'original release gate did not pass: '+job['name'])
    require(sum(j['name'] == 'Publish validated wheels to PyPI' for j in jobs['jobs']) == 1,
            'original publisher inventory changed')
    tag = gh('git/ref/tags/v1.0.3')['object']
    require(tag['type'] == 'tag' and tag['sha'] == TAG_OBJECT, 'release tag moved or was replaced')
    require(gh('git/tags/'+TAG_OBJECT)['object'] == {'sha': COMMIT, 'type': 'commit',
            'url': 'https://api.github.com/repos/'+REPO+'/git/commits/'+COMMIT}, 'tag target differs')
    artifact = gh('actions/artifacts/'+str(ARTIFACT))
    require(artifact['name'] == 'python-release-wheels' and not artifact['expired']
            and artifact['digest'] == 'sha256:'+ZIP_SHA256
            and artifact['workflow_run']['id'] == RUN
            and artifact['workflow_run']['head_sha'] == COMMIT,
            'original artifact identity/digest mismatch')
    print('PASS original release run, 44 successful gates, tag and artifact identity')


def sha(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def unpack_original(archive, output):
    require(sha(archive) == ZIP_SHA256, 'original artifact ZIP hash mismatch')
    with zipfile.ZipFile(archive) as zipped:
        require(len(zipped.infolist()) == len(EXPECTED)
                and {i.filename for i in zipped.infolist()} == set(EXPECTED),
                'original ZIP inventory differs')
        # Read and authenticate every member before creating any publication output.
        contents = {name: zipped.read(name) for name in EXPECTED}
        require(all(hashlib.sha256(data).hexdigest() == EXPECTED[name] for name,data in contents.items()),
                'distribution bytes differ from verified original hashes')
    Path(output).mkdir(mode=0o700)
    for name, data in contents.items():
        with (Path(output)/name).open('xb') as file:
            file.write(data)
    print('PASS original ZIP digest and all 17 distribution SHA-256 hashes')


def public_files():
    url = 'https://pypi.org/pypi/omneum/1.0.3/json?recovery='+str(time.time_ns())
    with urlopen(Request(url, headers={'Cache-Control': 'no-cache'}), timeout=30) as response:
        document = json.load(response)
    require(document['info']['name'] == 'omneum' and document['info']['version'] == '1.0.3',
            'public project/version mismatch')
    records = document['urls']
    require(len({r['filename'] for r in records}) == len(records), 'duplicate public filename')
    require(all(r['filename'] in EXPECTED and r['digests']['sha256'] == EXPECTED[r['filename']]
                and not r['yanked'] for r in records), 'unexpected/yanked public file or hash mismatch')
    return {r['filename']: r for r in records}


def verify_public_bytes(records):
    for name, record in records.items():
        parsed = urlsplit(record['url'])
        require(parsed.scheme == 'https' and parsed.hostname == 'files.pythonhosted.org'
                and not parsed.username and not parsed.password, 'public artifact URL differs')
        digest = hashlib.sha256()
        size = 0
        with urlopen(record['url'], timeout=30) as response:
            while chunk := response.read(1024*1024):
                size += len(chunk)
                require(size <= 16*1024*1024, 'public file exceeds original artifact bounds')
                digest.update(chunk)
        require(size == record['size'] and digest.hexdigest() == EXPECTED[name],
                'anonymous public download hash/size mismatch: '+name)
    print('PASS anonymous public distribution bytes:', len(records))


def select_missing(records):
    missing = set(EXPECTED)-set(records)
    require(missing <= ALLOWED_MISSING, 'publication selection includes an unapproved file')
    return sorted(missing)


def prepare():
    verify_origin()
    archive = Path('original-artifact.zip')
    with archive.open('xb') as file:
        subprocess.run(['gh','api','repos/'+REPO+'/actions/artifacts/'+str(ARTIFACT)+'/zip'],
                       stdout=file,check=True)
    original = Path('original-distributions')
    unpack_original(archive, original)
    records = public_files()
    verify_public_bytes(records)
    missing = select_missing(records)
    publish = Path('missing-distributions')
    publish.mkdir(mode=0o700)
    for name in missing:
        shutil.copyfile(original/name, publish/name)
        require(sha(publish/name) == EXPECTED[name], 'staged distribution hash mismatch')
    print('ONLY MISSING FILES STAGED:', json.dumps(missing))
    Path('before-publication.json').write_text(json.dumps(records,indent=2)+'\n')
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:
        file.write('needed='+('true' if missing else 'false')+'\n')


def pre_upload():
    records = public_files()
    missing = set(select_missing(records))
    staged = list(Path('missing-distributions').iterdir())
    require(all(p.is_file() and p.name in ALLOWED_MISSING and sha(p) == EXPECTED[p.name]
                for p in staged), 'staged upload inventory/hash mismatch')
    for path in staged:
        if path.name in records:
            path.unlink()  # Remove only a staged local copy; never touch PyPI/originals.
    require({p.name for p in Path('missing-distributions').iterdir()} == missing,
            'missing/publication staging changed unexpectedly')
    require(missing, 'nothing remains missing; stop before uploader')
    print('PASS final upload selection contains only missing original files:', sorted(missing))


def verify_final():
    records = public_files()
    require(set(records) == set(EXPECTED), 'PyPI publication remains incomplete')
    verify_public_bytes(records)
    verify_origin()
    Path('after-publication.json').write_text(json.dumps(records,indent=2)+'\n')
    print('PASS all 17 original distributions are public and byte-identical; tag unchanged')


if __name__ == '__main__':
    commands = {'prepare': prepare, 'pre-upload': pre_upload, 'verify-final': verify_final}
    require(len(sys.argv) == 2 and sys.argv[1] in commands, 'choose a fixed recovery phase')
    commands[sys.argv[1]]()
