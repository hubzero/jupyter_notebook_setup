# jupyter_notebook_setup: Rocky Linux 10 port

`jpkg` builds the Anaconda-based Jupyter installation used on the hubs. The installation includes
the classic Notebook, JupyterLab, kernels, extensions and the `start_jupyter` / `start_jupyterlab`
launchers.

These changes were meant to be **the minimal set that makes `jpkg install 7` work on Rocky Linux
10**. The target stays the same: Anaconda3-2020.11 (Python 3.8), JupyterLab 3.2.1 and Notebook 6.4.6.
Nothing was upgraded unless it had to be. Code or config was changed only where it actually broke,
and each change carries a comment saying why.

On a stock Rocky Linux 10.2 container, the result was checked end to end:

- `jpkg --desktop install 7` completes from scratch, with exit status 0, in about 75 minutes.
- The classic Notebook server serves `/tree`, notebooks, and the appmode `/apps/` view.
- JupyterLab serves `/lab`, and all 14 of its extensions report `enabled OK`.
- The `python3` and `octave` kernels both execute code.

## Host prerequisites (Rocky Linux 10)

```sh
dnf install -y which bzip2 tar xz curl git patch findutils procps-ng acl glibc-langpack-en python-unversioned-command gcc
# optional, for the octave kernel:
dnf install -y epel-release && crb enable && dnf install -y octave
```

Why each package is needed:

- `python-unversioned-command` provides `/usr/bin/python`, which the `#!/usr/bin/env python` scripts
  need.
- `gcc` builds the packages that have no Python 3.8 wheel: GPy, cymysql and mysqlclient.
- `acl` provides `setfacl`, used by `nbextensions/inboxes.py`.
- `glibc-langpack-en` provides the `en_US.UTF-8` locale that `jpkg` sets.

The same list is kept in the comment at the top of `jpkg`. The Docker tests read it from there.

## What was changed

### Rocky 10 and Python 3 compatibility

- **Paths:** The default OS directory is now `rocky10`. It was `debian10` in `jpkg` and `debian7` in
  `configs/nbnovnc`. The hub default envdir is therefore `/apps/share64/rocky10/environ.d`.
- **Python 3 bugs:** Rocky 10 has no Python 2. Under Python 3, `subprocess.check_output` returns
  bytes, so `.decode()` was added in several places:
  - octave detection in `jpkg` (before this, octave was always reported as missing);
  - the `ps auxwwe` session recovery in `start_jupyter` and `start_jupyterlab`.

  Python 3.12 also warned about invalid escape sequences, which are now written as raw strings.
- **Anaconda's linker:** `compiler_compat/ld` in Anaconda 2020.11 is binutils 2.33. It can't read the
  `.relr.dyn` sections in Rocky 10's glibc, so any C extension that pip builds fails to link.
  `jpkg install` now deletes it right after running the Anaconda installer, and gcc then uses the
  system linker. This is the one fix that's specific to Rocky 10.
- **Installer download:** `curl -O` became `curl -f -L -O`. `repo.continuum.io` now redirects, and
  `-f` stops an HTTP error page from being saved and run as the installer.

### Error checking in `jpkg install`

Before this change, every step ran through `os.system` and its result was ignored. A failed step
just scrolled past in the output. Now:

- Before downloading anything, `install` checks that every config file the selected options need
  exists. It lists any that are missing and exits. For example, `install 7 --with-nanohub` used to
  skip the missing `nanohub_*_7` files without saying so.
- The installer download, the installer itself, and every config file are checked. Configs are
  sourced with `set -e`, so the first failing line stops the install.
- `update` and the helper steps are not checked. The helper steps are the extension setup and
  `check_perm`. `check_perm`'s `find -L` reports broken symlinks, which Anaconda trees contain.

Turning on these checks exposed many config lines that had been failing without anyone noticing.
Most of the config changes below fix those lines.

### Removed

- **`jpkg netinst`.** It downloaded a prebuilt tarball from `packages.hubzero.org`. No `anaconda-7`
  tarball exists there. The only tarballs there, `anaconda2-5.1` and `anaconda3-5.1`, are Debian 7
  builds that only work at `/apps/share64/debian7/anaconda/...`: their `conda` and `jupyter` scripts
  and their kernel specs hard-code that path. The file names never matched what `netinst` requested.
- **`do_install()`.** Nothing called it, and it referenced functions that don't exist.

### Configs (`configs/*_7`, `configs/nbnovnc`)

The configs install packages mostly without versions. By 2026 that resolves to releases built for
Python ≥ 3.9 and JupyterLab 4. Each fix below caps a version. It does not pin to an exact version.

**JupyterLab 3 extensions.** JupyterLab 3 loads *prebuilt* extensions that ship inside pip
packages. Most `jupyter labextension install` lines were replaced by the matching pip package:

| Old `labextension install` line | Now |
|---|---|
| `@jupyter-widgets/jupyterlab-manager` | pip `"ipywidgets>=7.6,<8"` (brings `jupyterlab_widgets` 1.x) |
| `ipysheet` | pip `"ipysheet<0.6"` |
| `@jupyterlab/latex` | pip `"jupyterlab-latex<4"` |
| `@jupyterlab/geojson-extension` | pip `jupyterlab-geojson` |
| `@jupyterlab/vega3-extension` | pip `jupyterlab-vega3` |
| `jupyter-matplotlib` | pip `ipympl` (Python 3.8 limits it to 0.9.3) |
| `plotlywidget` | pip `"plotly<6"` (bundles `jupyterlab-plotly`) |
| `jupyterlab-floatview` | pip `floatview` 0.4.1 already bundles it |
| `jupyterlab-server-proxy` (`nbnovnc`) | pip `"jupyter-server-proxy<4"` |
| `jp_proxy_widget` | still built from npm: `"jp_proxy_widget@<2"` |
| `jupyterlab_iframe` | pip `"jupyterlab_iframe<0.4.3"` plus npm `"jupyterlab_iframe@<0.4.3"` (the 0.4.2 wheel has no front end) |
| `jupyterlab-spreadsheet` | still built from npm: `"jupyterlab-spreadsheet@<0.4.1"` |
| `jupyterlab-dash` (`dash_7`, never sourced) | still built from npm: `"jupyterlab-dash@<0.5"` |

The version ranges in the `labextension install` lines must stay quoted. `sh` treats a bare `<` as
a redirect.

**Node.** `jupyter labextension install` needs Node ≥ 12. The plain `conda install nodejs` gave Node
10.13.

- conda can't install Node 14 or 16 here. Those builds need `icu 68`, and this Anaconda's Qt is tied
  to `icu 58`. The solve didn't finish in 20–50 minutes.
- The config now installs `nodejs=12.4` from conda-forge, which has no icu dependency, together with
  `npm@6`. The current npm doesn't run on Node 12.

**Other version caps**, each needed to get the install through or to keep the Notebook working:

| Line | Cap | Reason |
|---|---|---|
| `base_pip_7` first line | `"pip<24.1"` | pip 20.2 doesn't fall back to older releases. pip 24.1+ refuses Anaconda's `pyodbc 4.0.0-unsupported`. |
| `black` | `"black>=21.12b0,<22.1"` | black 22.1+ needs click 8, which breaks `celery 5.0.5` |
| `moviepy` | `"moviepy<2"` | moviepy 2.x needs numpy ≥ 1.25, which has no Python 3.8 release |
| `nteract-scrapbook` | `"traitlets<5.10"` | Notebook 6.4 crashes at startup with traitlets ≥ 5.10 |
| GPy | `"GPy<1.13"` from PyPI, not GitHub | The GitHub source needs numpy ≥ 2 (Python ≥ 3.10) |
| `cymysql` | `"cymysql<1.1"` | 1.1+ uses Python 3.9 syntax without declaring it |
| `mysqlclient` | `"mysqlclient<2.2"` | 2.2+ finds MySQL only through pkg-config; 2.1 uses conda's `mysql_config` |
| `sphinx` | `"jinja2<3.1"` | Jinja2 3.1 removed `contextfilter`, which Notebook 6.4's nbconvert templates use |
| `appmode` | `"appmode<1"` | 1.0+ has no classic Notebook server extension, which `start_jupyter -A` needs |
| `oct2py` (`base_conda_7`) | `"ipyparallel<8.5"` | ipyparallel 8.6's JupyterLab extension needs JupyterLab ≥ 3.6.3 |

## What couldn't be ported

These have no version that works with JupyterLab 3.2.1 and Node 12.4 on Rocky 10. Each is commented
out in its config, with the reason.

- **`qgrid` JupyterLab extension** (`base_conda_7`): the newest npm release, 1.1.1 from 2018, needs
  `@jupyter-widgets/base ^1`. The qgrid Python package is still installed; its classic-notebook
  widget was not tested.
- **`@jupyterlab/mp4-extension`**: its only release (0.1.0, 2018) is for JupyterLab 0.x.
- **`jupyterlab-chart-editor`**: 4.14.3 supports JupyterLab 3, but its dependencies now pull in
  `@mapbox/jsonlint-lines-primitives`, which requires Node ≥ 22. The build fails with Node 12.4.
  Turning off yarn's engine check might get it built, but it would have to stay off for every
  future JupyterLab rebuild, so that wasn't done.
- **`@mflevine/jupyterlab_html`**: last released in 2018. JupyterLab 3 has a built-in HTML viewer.
- **`@jupyterlab/plotly-extension`**: last released in 2019. It's replaced by the `jupyterlab-plotly`
  extension bundled with plotly 5.
- **`jpkg netinst`**: removed; see above.
- **Node 16**: not installable through conda in this Anaconda, so Node 12.4 is used instead (see
  above).
- **Current releases of the capped packages**: the tables above keep these at older versions. A new
  release of a package that isn't capped can still break the install.

Also unavailable for version 7, but already missing before this work: `--with-nanohub`, `--with-ml`
and `--with-py2` have no `_7` config files. `install` now refuses those options for 7 instead of
skipping them silently. `--with-dash` is accepted but never sources `dash_7`.

## Not tested

- **Other `install` options:** only `jpkg --desktop install 7` with no other options was run end to
  end. `--with-r` (`r_7`), `--with-vnc` (`nbnovnc`), and the hub (non-`--desktop`) path were not.
- **Browser use:** JupyterLab and the extensions were checked from the command line and by fetching
  pages. Nobody used them in a browser.
- **`update`** was not run.

## Tests

`tests/docker/` runs the scripts in a stock `rockylinux/rockylinux:10` container. The image is built
from the prerequisite list in `jpkg`, plus octave from EPEL, and the tests run as an unprivileged
user.

```sh
tests/docker/run-docker-test.sh              # the whole suite (a few minutes, mostly the image build)
tests/docker/run-docker-test.sh --anaconda   # also download and run the Anaconda 2020.11 installer
tests/docker/run-docker-test.sh --offline    # skip the tests that need the network
tests/docker/run-docker-test.sh --keep       # leave the container running afterwards
```

The suite covers the following:

- the prerequisites;
- syntax warnings under Python 3.12;
- octave detection;
- the launchers' session handling;
- `install`'s error checking, using a fake installer and fake configs.

It does not run a full `install 7`, which takes over an hour. To run one by hand, using the image
that `run-docker-test.sh` builds:

```sh
docker run -d --name jt --network host jupyter-setup-rocky10-test:latest
docker exec jt mkdir -p /opt/jupyter_notebook_setup /home/jupytest/build
tar --exclude=.git -cf - . | docker exec -i jt tar -C /opt/jupyter_notebook_setup -xf -
docker exec jt chown -R jupytest:jupytest /opt/jupyter_notebook_setup /home/jupytest/build
docker exec -u jupytest -w /home/jupytest/build -e PYTHONUNBUFFERED=1 jt \
    /opt/jupyter_notebook_setup/jpkg --desktop install 7
```

`PYTHONUNBUFFERED=1` keeps `jpkg`'s own messages in order with the conda and pip output when the
output is logged to a file.
