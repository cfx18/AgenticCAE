# Kimi K3 failure analysis using Astra Ultra as a pseudo-ground truth

Date: 2026-09-16

## Scope and validity

The Astra Ultra minimal-autonomous run is treated as a pseudo-ground truth for causal
diagnosis, not as the unavailable author CAD. Paper-explicit and analytically closed
quantities are stronger references than Astra-specific interpolation choices. Differences
in an under-specified loft convention must remain uncertainty rather than being counted
automatically as Kimi errors. The earlier detailed-prompt Astra run independently produced
the same principal analytical quantities and is supporting evidence, not the prompt used for
the primary comparison.

After replacing the run-directory name with a placeholder, the Astra and Kimi action prompts
are byte-for-byte identical. They also use the same PDF hash and the audited AutoCAD MCP.
This is therefore a valid comparison of the two complete agent systems under the same minimal
task instruction. It is still not a pure base-model comparison because Astra ran through the
Codex harness and Kimi through Kimi Code.

## What Kimi got right

- Metering diameter D = 7.75 mm.
- Axis inclination alpha = 30 degrees.
- Metering length Lm/D = 2.5 and diffuser length 3.5D.
- Symmetric lateral 7-degree expansion and one-sided forward 7-degree expansion.
- Effective diffuser-floor angle of 23 degrees.
- R/D = 0.5 endpoint profile rounding.
- Native AutoCAD solids, a real Boolean subtraction, and final topology export.

The intrinsic endpoint profile is not the main failure. Kimi's untrimmed B-B dimensions
(14.411 mm by 11.081 mm) agree with Astra's analytical untrimmed section at s/D = 6.

## First causal divergence

Kimi introduced an unsupported plate thickness T = 1.5D before CAD construction. It treated
plate thickness as missing, even though the Figure 1 station semantics permit the relation

    H = L sin(alpha) = 6D sin(30 degrees) = 3D.

This is the first material divergence from the Astra reference. It is a paper-to-geometric-IR
reasoning error, not an AutoCAD execution error.

The wrong thickness then changed the physical meaning of the nominal stations:

- Kimi placed the top plate face only 3D of axial travel from the bottom-face centerline
  intersection, only 0.5D into the diffuser.
- Astra places the two plate faces 6D apart along the axis, so the full nominal hole length
  lies through the plate.
- Kimi treated the complete B-B endpoint section as A_exit. Astra distinguishes B-B from the
  physical exit section at the upstream breakout station, where AR is about 2.5017.

## Constraint-reconciliation failure

Kimi computed B-B area / metering area = 3.11 while the paper reports AR = 2.5. This was
valuable evidence, but the agent converted the contradiction into a speculative note about
"another convention" and continued. It did not enumerate candidate definitions, evaluate
the physical breakout plane, or use the reported AR and coverage ratio to select between
interpretations.

This is a verifier-policy failure as well as a model reasoning failure: a primary
dimensionless paper constraint was allowed to remain violated while the run still declared
success.

## Solid-representation failure

Kimi terminated the positive passage at nominal section planes rather than extending the
passage beyond both plate faces and intersecting it with the host slab. At the underside,
the oblique metering cap therefore clips the inlet to a half ellipse. Astra uses sacrificial
extensions, then intersects with the slab, so nominal stations do not create artificial caps
in the final CAE fluid domain.

Kimi also delivered one review-style DWG containing the cut plate, the overlapping full void,
and construction curves. It did not provide an isolated, clipped, watertight fluid-domain
solid as a separate CAE deliverable.

## Quantified physical consequences

Using the plate-removed volume and planar opening areas as like-for-like physical quantities:

- Plate thickness: Kimi 11.625 mm versus Astra 23.25 mm, or 50 percent of the reference.
- Fluid volume inside the plate: Kimi 1120.471 mm3 versus Astra 4104.897 mm3, or 27.3 percent.
- Underside inlet opening: Kimi 47.173 mm2 versus Astra 94.346 mm2, or 50 percent.
- Hot-surface breakout area: Kimi 140.054 mm2 versus Astra 375.439 mm2, or 37.3 percent.

Kimi's full VOID volume of 3415.809 mm3 is not a valid substitute for the physical fluid
volume because parts lie outside its plate and its section-plane caps are part of the error.

## Verification failure

Kimi's final checks establish internal CAD consistency, not paper fidelity. The expected
values were calculated from the same assumed 1.5D construction that generated the model.
Consequently, topology, volume, and endpoint-area checks all passed without challenging the
wrong interpretation.

Missing independent checks were:

- H/D derived from L/D and alpha.
- A_inlet at the physical underside plane.
- A_exit and AR at the paper-defined breakout station.
- Top-surface breakout area and t/P coverage.
- A(s), width(s), and height(s) at multiple normal sections.
- A rendered side section showing both plate faces and named stations.
- Saved Model-space view and Zoom Extents before final delivery.

## Tool and harness effects

The Kimi run issued 17 Core Console starts. At least 6 did not reach the save sentinel, and
the outer process required two resumptions. The total wall time was about 130 minutes. Kimi
recovered from AutoLISP symbol collisions, UCS/LOFT problems, non-overlapping solids, and
SAVEAS/wrapper semantics. This demonstrates useful execution debugging, but it also consumed
attention without reopening the earlier scientific interpretation.

The shared minimal prompt did not require a constraint ledger, contradiction gate, separate
CAE deliverables, analytical section checks, render inspection, or a failure state for
unresolved primary constraints. Astra created these controls autonomously; Kimi did not.
That difference is meaningful evidence about the two agent systems. Attribution to the base
models alone still requires a common harness.

Astra minimal completed in about 20.7 minutes. Kimi required about 130 minutes including two
resumptions. Runtime is not a direct quality metric, but the difference supports the observed
tool-planning and recovery-cost gap.

## Causal classification

Primary cause:

- Geometric-IR semantics: wrong plate thickness and confusion between B-B and A_exit.

Secondary causes:

- Constraint reasoning: rationalized AR conflict instead of testing interpretations.
- Construction planning: no sacrificial passage extensions before slab intersection.
- Verifier design: self-consistency oracle shared the candidate's assumptions.

Tertiary causes:

- AutoCAD execution fragility and unclear Core Console save contract.
- Deliverable/view-state omission.

Not yet proven to be a Kimi failure:

- Exact diffuser interpolation between profiles, because the paper does not expose the author
  CAD and Astra documents this as its highest-impact residual uncertainty.

## Counterfactual localization experiments

Run the same Kimi K3 model through an intervention ladder while keeping the AutoCAD MCP and
reasoning budget fixed:

1. PDF only, same minimal prompt: reproduce the observed end-to-end result.
2. Gold evidence ledger only: provide extracted facts and source locations, but no derivations.
3. Gold geometric IR: additionally provide H=3D, station definitions, A_exit meaning, and
   required invariant equations, but no CAD operations.
4. Gold feature graph: additionally specify extend-passage, intersect-slab, subtract-host, and
   isolate-fluid intent, but let Kimi author all AutoCAD code.
5. Gold AutoCAD program: execute a known construction to isolate MCP and harness reliability.

Interpretation:

- Success first at step 2 localizes failure to paper perception/evidence extraction.
- Success first at step 3 localizes it to geometric reasoning and constraint closure.
- Success first at step 4 localizes it to construction planning.
- Success only at step 5 localizes it to CAD code generation or tool use.
- Failure at step 5 localizes it to the MCP/harness/runtime rather than the model.

The same-minimal-prompt condition is already complete. For a pure model comparison, run both
models through one common harness with the same tool schemas, context policy, and stop rules.
A second shared structured-prompt condition would then separate autonomous workflow induction
from compliance with an explicit workflow.

## Evidence paths

- Astra minimal prompt: `runs/thole-baseline-hole-astra-ultra-minimal-20260916/attempts/a001/action-prompt.md`
- Astra minimal analytical check: `runs/thole-baseline-hole-astra-ultra-minimal-20260916/outputs/reconstruction/verification/independent_geometry_check.json`
- Astra minimal reconstruction report: `runs/thole-baseline-hole-astra-ultra-minimal-20260916/outputs/reconstruction/README.md`
- Supporting detailed Astra report: `runs/thole-baseline-hole-astra-ultra-20260915/attempts/a001/geometry-report.json`
- Kimi prompt: `runs/thole-baseline-hole-kimi-k3-minimal-20260916-r3/attempts/a001/action-prompt.md`
- Kimi trajectory: `runs/thole-baseline-hole-kimi-k3-minimal-20260916-r3/attempts/a001/kimi-events.jsonl` plus the two resume event files
- Kimi interpretation: `runs/thole-baseline-hole-kimi-k3-minimal-20260916-r3/outputs/ASSUMPTIONS.md`
- Kimi final B-Rep: `runs/thole-baseline-hole-kimi-k3-minimal-20260916-r3/outputs/topology-final.json`
