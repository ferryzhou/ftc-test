# BIOBUZZ bot code

Robot code for the goBILDA StarterBot 3200-2627-0004 modified for POLLEN and NECTAR.
The mechanical changes and the hardware configuration are documented in
[`doc/biobuzz-bot/README.md`](../../../../../../../../../doc/biobuzz-bot/README.md).

| file | role |
|---|---|
| `BioBuzzConfig.java` | every device name and tunable number |
| `BioBuzzRobot.java` | hardware layer: mecanum drive, intake, launcher, hood, element sensor, element queue |
| `BioBuzzTeleOp.java` | driver op mode |
| `BioBuzzAuto.java` | launch the four pre-loaded POLLEN, then LEAVE |
| `ElementKind.java`, `Alliance.java` | small enums; the alliance choice carries from auto to teleop |

Behaviour that is not in goBILDA's sample:

- The colour sensor in the chute classifies each ball. Opponent NECTAR reverses the intake for
  `REJECT_SECONDS` (G408). The intake stops at `MAX_ELEMENTS` = 4 (G407).
- Elements are queued first-in-first-out, so the hood servo and launcher velocity are set for the
  ball about to be fed, and the windmill only turns once the wheel is up to that ball's minimum
  velocity and the hood has settled.
- Missing devices are reported in telemetry instead of crashing the op mode.
