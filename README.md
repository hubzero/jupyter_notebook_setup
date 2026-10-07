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

`jpkg install 8` is the opposite: a fully up-to-date stack on Miniforge (Python 3.14), JupyterLab 4
and Notebook 7. See [Version 8](#version-8-current-releases). Version 7 is unchanged.

## Host prerequisites (Rocky Linux 10)

```sh
dnf install -y which bzip2 tar curl git findutils procps-ng glibc-langpack-en python-unversioned-command gcc
# optional, for the octave kernel:
dnf install -y epel-release && crb enable && dnf install -y octave
```

Why each package is needed:

- `python-unversioned-command` provides `/usr/bin/python`, which the `#!/usr/bin/env python` scripts
  need.
- `gcc` builds the packages that have no Python 3.8 wheel: GPy, cymysql and mysqlclient.
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
  `check_perm`. `check_perm`'s world-writable pass (`find -L`) skips broken symlinks with
  `! -type l`. conda's `pkgs/` cache has many of them, and `chmod` would fail on each one.

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

## Version 8: current releases

`jpkg [--with-r] install 8` (configs `base_conda_8`, `base_pip_8`, `r_8`) installs current releases of
everything, with no version caps. These 15 packages are required, and each one is at its newest
release:

| Package | Version | | Package | Version |
|---|---|---|---|---|
| pyvista[jupyter] | 0.49.0 (vtk 9.7.0) | | jupyterlab | 4.6.4 |
| imageio | 2.38.0 | | matplotlib | 3.11.2 |
| numpy | 2.5.3 | | burnman | 2.1.0 (pip, `--no-deps`; see [below](#burnman-with---no-deps)) |
| pandas | 3.0.6 | | autograd | 1.9.1 |
| scipy | 1.18.1 | | ipywidgets | 8.1.9 |
| meshio | 5.3.5 | | widgetsnbextension | 4.0.16 |
| tables | 3.11.1 | | cmcrameri | 1.10 |
| cartopy | 0.26.0 | | | |

The versions are as of 2026-10-01. Each other package from the version 7 configs was kept, at its
current release, if it works alongside these. The ones that don't are dropped; see
[below](#dropped-from-version-8).

### What's different from 7

- **Miniforge, not Anaconda.** `base_conda_8`'s `#ver=` line is the full URL of the Miniforge
  installer (26.7.2-0). `jpkg` downloads any `#ver=` that is a URL as it is; a bare file name still
  comes from the Anaconda archive, as for 7. Everything comes from conda-forge, so the defaults
  channel and its terms of service are out of the picture.
- **Channels locked to conda-forge.** The installing account's `~/.condarc` can still add
  `defaults`. For a `#ver=` URL, `jpkg install` and `jpkg update` add `#!final` to the `channels:`
  line of the install's `.condarc` and set `channel_priority: strict   #!final`, so later config
  files can't change either setting. conda only honors `#!final` on the key's own line. `update`
  fixes the channels of an existing install but not packages already installed from `defaults`.
  `conda list --show-channel-urls | grep -v conda-forge` lists those.
- **Python 3.14.** Current numpy and scipy need Python ≥ 3.12, and vtk has no build for 3.15.
- **One conda solve for the required stack**, so vtk, proj/geos and hdf5 come out consistent.
- **No Node.** JupyterLab 4 extensions are prebuilt and ship in their pip or conda packages, so no
  config line runs `jupyter labextension install`.
- **Notebook 7 plus nbclassic.** Notebook 7 has no classic server. nbclassic 1.3 serves the classic
  UI on jupyter_server, under `/nbclassic/` because Notebook 7 is installed too. The parts that need
  the classic UI keep working with it: `start_jupyter`, appmode 1.3 (`/apps/`), widgetsnbextension and
  the nbextensions (snippets, Calysto, `prefs`).
- **`start_jupyter`** reads the installed notebook version. With Notebook 7 it runs
  `jupyter nbclassic` with `--ServerApp.base_url`, `--IdentityProvider.token` and
  `--NotebookApp.default_url=nbclassic/notebooks/<nb>`. The default URL stays a `NotebookApp` option
  because nbclassic copies its own `NotebookApp.default_url` over `ServerApp.default_url`. With
  Notebook 6 the command is unchanged.
- **`start_jupyterlab`** passes `--ServerApp.base_url` instead of `--NotebookApp.base_url`.
  JupyterLab 3 and 4 both run on jupyter_server.
- **`install_extensions`** checks whether the install has `bin/jupyter-nbextension` (7 does, 8
  doesn't). Without it:
  - the server settings (`trust_xheaders`, `disable_check_xsrf`, the hub's `login_handler_class`)
    go into `etc/jupyter/jupyter_server_config.py`;
  - the classic-UI settings stay in `jupyter_notebook_config.py`;
  - the extensions are installed with `jupyter nbclassic-extension`.
- **`hublogin.py`** chooses its base classes from the notebook version. It can't just try the
  import: nbclassic's import shims answer `import notebook.base.handlers` even with Notebook 7. On
  jupyter_server it subclasses `LegacyLoginHandler`, because jupyter_server 2's
  `LegacyIdentityProvider` calls `get_login_available`, `should_check_origin` and
  `is_token_authenticated` on the login handler class.

### Packages that needed help

| Package | What was done |
|---|---|
| burnman | Not on conda-forge, and its last release (2.1.0, Nov 2024) declares numpy < 2 and numba 0.59 (Python ≤ 3.12). It's installed with `pip install --no-deps burnman`, so pip ignores those pins. numba (current release), cvxpy and sympy come from conda-forge. numba can't be left out: 2.1.0's no-numba fallback is broken, so `import burnman` fails without it. See [burnman with `--no-deps`](#burnman-with---no-deps). |
| dask | Needs the floor `dask>=2026.8`. Without it conda picks dask 2023.3 and bokeh 2.4 instead of moving hdf5 from 2.2 back to 1.14, which current pyarrow still needs. hdf5 is therefore 1.14.6. pytables, h5py and vtk keep their versions and get rebuilt variants. |
| mysqlclient | Built by pip against conda-forge's mysql 9.7.1, through conda-forge's `pkg-config`. conda-forge's own mysqlclient (2.2.8) would pull mysql back to 9.6. |
| ffmpeg | 8.1.2, not 9.0.2: ffmpeg 9 would pull mysql back from 9.7.1. Neither is a required package. |
| pyvista[jupyter] | The extra now pulls in `trame-pyvista`, which pins trame to 3.13.2 (4.0.0 is out). |
| RISE | Replaced by `jupyterlab-rise` 0.43.1. That package pulls in `jupyterlab-mathjax3`, a JupyterLab 3 extension, and JupyterLab 4 lists it as `X` and skips it. JupyterLab 4 renders MathJax itself. |
| jupyterlab-spreadsheet | The npm extension became pip `jupyterlab-spreadsheet-editor` 0.7.2. |
| plotly_express | Part of plotly (7.1.0) now; the line is gone. |
| jupyter_leaflet | ipyleaflet's front end. Pinned to `conda-forge/noarch::jupyter_leaflet`, because Anaconda's build installs into `lib/python3.10`, which Python 3.14 never loads. An install whose `~/.condarc` added `defaults` may have Anaconda's build. To fix it, run `jpkg update 8`, then `anaconda-8/bin/conda install -y --force-reinstall conda-forge/noarch::jupyter_leaflet`, then delete what's left in `lib/python3.10`. |
| R (`r_8`) | Same as `r_7`, but conda-forge only: r-base 4.5.3, rpy2 3.6.8. |

### burnman with `--no-deps`

`base_pip_8` runs `pip install --no-deps burnman`. burnman 2.1.0 declares numpy < 2 and numba 0.59,
which would make pip downgrade numpy (and fail on Python 3.14). `--no-deps` skips its declared
dependencies, so it uses conda-forge's numpy 2, numba, scipy, matplotlib, cvxpy and sympy. With
numpy 2.5.3 and numba 0.68, forsterite at 10 GPa and 1500 K comes out at 3362.47 kg/m³. That's the
same as with burnman's GitHub `main`. `pip check` reports burnman's numpy and numba pins as unmet.
That's expected.

numba is required even though burnman's numba imports are optional. In 2.1.0, the stand-in it
defines when numba is missing is `def jit(fn)`, but every use is `@jit(nopython=True)`, so
`import burnman` raises `TypeError: jit() got an unexpected keyword argument 'nopython'`.
`NUMBA_DISABLE_JIT=1` takes the same path and fails the same way.

**Updating an existing install.** `jpkg update 8` doesn't touch burnman, because `update` never
re-runs `base_conda_8` or `base_pip_8`. To update it by hand:

```sh
anaconda-8/bin/pip install -U --no-deps burnman
```

If a new release needs newer versions of its dependencies, install those with conda first. Then
run a smoke test:

```sh
anaconda-8/bin/python -c "import burnman; m = burnman.minerals.SLB_2011.forsterite(); m.set_state(10e9, 1500.); print(m.density)"
```

### Dropped from version 8

Each one is commented out in its config with the reason.

| Package | Last release | Why it was dropped |
|---|---|---|
| qgrid | 1.3.1 (2020) | Needs ipywidgets 7 and widgetsnbextension 3 |
| floatview | 0.4.1 (2023) | Needs ipywidgets 7 and widgetsnbextension 3; JupyterLab 3 extension |
| gmaps | 0.9.0 (2019) | Only a source lab extension for `@jupyter-widgets/base` 2 (JupyterLab ≤ 2); ipywidgets 8 is base 6 |
| ipysheet | 0.7.0 (2022) | JupyterLab 3 extension (lumino 1), which JupyterLab 4 won't load |
| jp_proxy_widget | 1.0.10 (2021) | No JupyterLab 4 extension; widget front end needs `@jupyter-widgets/base` 2–4 |
| scikit-video | 1.1.11 (2018) | Writes video with `ndarray.tostring`, which numpy 2 removed |
| mapboxgl | 0.10.2 (2019) | Imports `IPython.core.display.display`, which IPython 9 removed |
| RISE (classic) | 5.7.1 (2020) | Notebook < 7 only; replaced by `jupyterlab-rise` |
| nodejs, npm | | Nothing builds a lab extension any more |
| tornado (explicit line) | | Comes with jupyter_server |

The JupyterLab 3 workarounds from 7 are gone too, for `jupyterlab_iframe`, `jupyterlab-latex`,
`jupyterlab-geojson`, `jupyterlab-vega3` and `ipympl`. Their current releases support JupyterLab 4.
`dash_7` has no `dash_8`, because `--with-dash` never sources a dash config.

### Checked for version 8

On the test image (stock Rocky Linux 10 plus the prerequisites), as an unprivileged user:

- `jpkg --desktop --with-r install 8` completes from scratch, with exit status 0, in about 7 minutes.
- **Required packages:** all 15 import at the versions above.
  - pyvista renders off-screen to PNG. No system GL libraries were needed: vtk warns that there is
    no X server and falls back by itself.
  - cartopy draws a coastline map with `cmcrameri.cm.batlow`.
  - burnman computes forsterite's density at 10 GPa and 1500 K.
  - autograd takes a gradient.
  - pandas and tables write and read HDF5.
  - meshio and imageio write and read files.
- **Other packages:** the kept ones import, and oct2py runs octave. `pip check` finds no broken
  requirements. With burnman now installed with `--no-deps`, it also reports burnman's numpy and
  numba pins (expected).
- **Kernels:** `python3`, `octave` and `r` are installed.
- **JupyterLab:** every extension reports `enabled OK` except `jupyterlab-mathjax3` (see above).
  That includes `@jupyter-widgets/jupyterlab-manager` 5.0.16, plotly, ipympl, leaflet,
  ipyparallel, RISE, LaTeX and the spreadsheet editor.
- **Launchers, with a faked hub session:**
  - `start_jupyter -A tool.ipynb` redirects `/` to `…/apps/tool.ipynb`.
  - `start_jupyter tool.ipynb` redirects `/` to `…/nbclassic/notebooks/tool.ipynb`.
  - `/tree` and `/lab` answer under the `/weber/…/` base URL.
  - `start_jupyterlab` serves `/lab` under that base URL.
- **Hub login (`hublogin.py` on jupyter_server 2):**
  - the first browser gets the `weber-auth-*` cookie;
  - a second browser without it is redirected to `/login` ("Access Forbidden");
  - the cookie or the URL token gets in;
  - a wrong cookie gets 403.

Not tested for 8: use in a browser, so nothing checks that widgets, trame/pyvista or the nbextensions
render. Also not tested: the full hub (non-`--desktop`) install, `--with-vnc` (`nbnovnc`) and
`update`.

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
- the launchers' session handling, and the command `start_jupyter` builds for Notebook 6 and 7;
- `install`'s error checking, using a fake installer and fake configs;
- installers named by URL, the version 8 configs, and the Miniforge download.

It does not run a full `install 7`, which takes over an hour, or `install 8` (about 7 minutes). To
run one by hand, using the image that `run-docker-test.sh` builds (`install 8` works the same way):

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
