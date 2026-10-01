"""Small decision-test backend: supplied paths keyed by realized implementation.

No HDL/tool subprocesses. The caller supplies timing rules, allowing the same
fixture to expose either its single worst clock path or all independent paths.
"""

from types import SimpleNamespace
import SWEEP


class ScriptedBackend:
    def __init__(self, rule, multiple=False):
        self.rule = rule
        self.multiple = multiple
        self.calls = []
        self.__name__ = "SCRIPTED"

    def SYN_AND_REPORT_TIMING_MULTIMAIN(self, parser_state, params):
        signature = SWEEP.IMPLEMENTATION_SIGNATURE(parser_state, params)
        if signature in self.calls:
            raise AssertionError("Redundant synthesis of " + signature)
        self.calls.append(signature)
        paths = sorted(self.rule(parser_state, params), key=lambda p: -p.path_delay_ns)
        worst = {}
        for path in paths:
            worst.setdefault(path.path_group, path)
        return SimpleNamespace(
            path_reports=worst,
            extra_paths=paths if self.multiple else [],
            orig_text="scripted timing",
            reg_merged_with={},
            coverage={"scripted": {"complete": self.multiple}},
            input_signature=signature,
            cache_hit=False,
        )


def path(main, delay, period=10.0, pair="logic"):
    return SimpleNamespace(
        start_reg_name=main + "/" + pair + "/launch[0]",
        end_reg_name=main + "/" + pair + "/capture[0]",
        path_group="clk_shared",
        path_delay_ns=delay,
        slack_ns=period - delay,
        requirement_ns=period,
        source_ns_per_clock=period,
        netlist_resources=set(),
        logic_levels=1,
    )
