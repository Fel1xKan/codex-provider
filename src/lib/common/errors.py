class SwitchError(RuntimeError):
    pass


class MissingConfigError(SwitchError):
    pass


class MissingModelProviderError(MissingConfigError):
    pass
