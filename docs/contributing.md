How to contribute
=================

plugin-hostd is developed in the open at [FreeMixer/plugin-hostd](https://github.com/FreeMixer/plugin-hostd).

- **Report a problem** as an [issue](https://github.com/FreeMixer/plugin-hostd/issues): what you ran, what you
  expected, what came back (the reply line or the event), and the versions of plugin-hostd and of the worker.
- **Change something** with a pull request against `main`. [BUILDING.md](../BUILDING.md) says how to build and which
  tests to run; every pull request runs the tests that need no audio server, builds the packages and installs them
  in a clean container. A fix comes with the test that fails without it.
- **Documentation** is the markdown under `docs/`: a new page is one file there and one entry in `docs/site.yml`,
  and the build of this site says by name what is missing or unreachable.

The code is GPL-3.0-or-later ([COPYING](../COPYING)).
