# validator.py — post-compose quality checks on the assembled stage. Reads the
# stage through pxr (Usd) only; emits plain Issue records the façade can act on.

from __future__ import annotations

from dataclasses import dataclass

from pxr import Usd

ERROR = "error"
WARN = "warn"


@dataclass(frozen=True)
class Issue:
    """One validation finding. *level* is ``error`` (blocks a strict write) or
    ``warn`` (logged, non-blocking); *prim* is the offending path when relevant."""

    level: str
    msg: str
    prim: str | None = None


class AssemblyValidator:
    """Check an assembled stage for the invariants a published root must hold.

    Deliberately in-memory and cheap: it verifies authoring the assembler is
    responsible for (defaultPrim, model kinds, dangling instances), not the
    resolvability of referenced files (that is the resolver's contract upstream).
    """

    #: Kinds that mark a model root and therefore require a defaultPrim + kind.
    _MODEL_ROOT_KINDS = frozenset({"component", "assembly"})

    def check(self, stage: "Usd.Stage") -> list[Issue]:
        issues: list[Issue] = []
        issues.extend(self._check_default_prim(stage))
        issues.extend(self._check_instances_reference(stage))
        return issues

    def _check_default_prim(self, stage: "Usd.Stage") -> list[Issue]:
        default = stage.GetDefaultPrim()
        if not default or not default.IsValid():
            return [Issue(ERROR, "stage has no valid defaultPrim", None)]

        issues: list[Issue] = []
        kind = Usd.ModelAPI(default).GetKind()
        if not kind:
            issues.append(
                Issue(ERROR, "defaultPrim has no kind", default.GetPath().pathString)
            )
        return issues

    def _check_instances_reference(self, stage: "Usd.Stage") -> list[Issue]:
        """An instance prim under a model root should carry a reference/payload.

        Catches an instance that was declared but never resolved to an asset
        (an empty placeholder that would silently vanish downstream).
        """
        issues: list[Issue] = []
        default = stage.GetDefaultPrim()
        if not default or not default.IsValid():
            return issues
        # A component's children are its own geometry (from the model sublayer),
        # not instance placeholders — the reference/payload check does not apply.
        if Usd.ModelAPI(default).GetKind() == "component":
            return issues
        for child in default.GetChildren():
            has_arc = child.HasAuthoredReferences() or child.HasPayload()
            if not has_arc:
                issues.append(
                    Issue(
                        WARN,
                        "instance carries no reference or payload",
                        child.GetPath().pathString,
                    )
                )
        return issues

    @staticmethod
    def has_errors(issues: list[Issue]) -> bool:
        return any(i.level == ERROR for i in issues)
