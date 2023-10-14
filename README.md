# Cadwyn

Modern [Stripe-like](https://stripe.com/blog/api-versioning) API versioning in FastAPI

---

<p align="center">
<a href="https://github.com/ovsyanka83/cadwyn/actions?query=workflow%3ATests+event%3Apush+branch%3Amain" target="_blank">
    <img src="https://github.com/Ovsyanka83/cadwyn/actions/workflows/test.yaml/badge.svg?branch=main&event=push" alt="Test">
</a>
<a href="https://codecov.io/gh/ovsyanka83/cadwyn" target="_blank">
    <img src="https://img.shields.io/codecov/c/github/ovsyanka83/cadwyn?color=%2334D058" alt="Coverage">
</a>
<a href="https://pypi.org/project/cadwyn/" target="_blank">
    <img alt="PyPI" src="https://img.shields.io/pypi/v/cadwyn?color=%2334D058&label=pypi%20package" alt="Package version">
</a>
<a href="https://pypi.org/project/cadwyn/" target="_blank">
    <img src="https://img.shields.io/pypi/pyversions/cadwyn?color=%2334D058" alt="Supported Python versions">
</a>
</p>

## Who is this for?

Cadwyn allows you to support a single version of your code, auto-generating the code/routes for older versions. You keep versioning encapsulated in small and independent "version change" modules while your business logic knows nothing about versioning.

Its approach will be useful if you want to:

1. Support many API versions for a long time
2. Effortlessly backport features and bugfixes to older API versions

Otherwise, more conventional methods of API versioning may be preferable.

## Get started

The [documentation](https://docs.cadwyn.dev) has everything you need to get started. It is recommended to read it in the following order:

1. Tutorial
2. Recipes
3. Reference (if needed)
<!--- 4. Theory (if you are interested) -->

## Similar projects

The following projects are trying to accomplish similar results with a lot more simplistic functionality.

* <https://github.com/sjkaliski/pinned>
* <https://github.com/phillbaker/gates>
* <https://github.com/lukepolo/laravel-api-migrations>
* <https://github.com/tomschlick/request-migrations>
* <https://github.com/keygen-sh/request_migrations>
