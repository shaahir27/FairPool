"""Provider failures shared by the identity port and its Sandbox implementation."""


class PayPalIdentityDeclined(Exception):
    """The provider rejected a grant; the browser must start again."""


class PayPalIdentityUnavailable(Exception):
    """The provider did not return usable identity evidence."""
