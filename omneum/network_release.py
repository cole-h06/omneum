"""Check release-owned public parameters without inventing provisioning values."""
import argparse
from urllib.parse import urlsplit


def validate_release(*, require_provisioned=False):
    from .contribution.network import _PRODUCTION_NETWORK, OmneumNetwork
    from .onboarding import _PRODUCTION_ONBOARDING, OnboardingPins
    if _PRODUCTION_NETWORK is None or _PRODUCTION_ONBOARDING is None:
        if require_provisioned:
            raise ValueError('production Network and account pins must be provisioned and verified')
        return False
    OmneumNetwork.pseudonymous(api_key='release-validation')
    pins = _PRODUCTION_ONBOARDING
    if type(pins) is not OnboardingPins:
        raise ValueError('invalid onboarding pins')
    pins.__post_init__()
    if not pins.audience:
        raise ValueError('release account audience required')
    ingestion = urlsplit(_PRODUCTION_NETWORK.ingestion_endpoint)
    voprf = urlsplit(_PRODUCTION_NETWORK.voprf_endpoint)
    enrollment = urlsplit(pins.enrollment_endpoint)
    def origin(value):
        return value.scheme, value.hostname, value.port or 443
    if origin(ingestion) != origin(voprf) or origin(ingestion) != origin(enrollment):
        raise ValueError('Network routes must share the release-owned origin')
    if [ingestion.path, voprf.path, enrollment.path] != ['/v1/contributions', '/v1/voprf', '/v1/enrollment']:
        raise ValueError('invalid release routes')
    import re
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', pins.consent_version):
        raise ValueError('invalid release consent version')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-provisioned', action='store_true')
    args = parser.parse_args()
    try:
        ready = validate_release(require_provisioned=args.require_provisioned)
    except Exception:
        raise SystemExit('Network release validation failed: check verified production public pins.') from None
    print('Public release configuration valid; live deployment verification still required.' if ready
          else 'Production Network onboarding is unprovisioned; contribution remains disabled.')


if __name__ == '__main__':
    main()
