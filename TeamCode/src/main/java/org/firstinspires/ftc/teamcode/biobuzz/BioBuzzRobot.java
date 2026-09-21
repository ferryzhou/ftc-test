package org.firstinspires.ftc.teamcode.biobuzz;

import static com.qualcomm.robotcore.hardware.DcMotor.ZeroPowerBehavior.BRAKE;

import android.graphics.Color;

import com.qualcomm.robotcore.hardware.CRServo;
import com.qualcomm.robotcore.hardware.DcMotor;
import com.qualcomm.robotcore.hardware.DcMotorEx;
import com.qualcomm.robotcore.hardware.DcMotorSimple;
import com.qualcomm.robotcore.hardware.DistanceSensor;
import com.qualcomm.robotcore.hardware.HardwareMap;
import com.qualcomm.robotcore.hardware.NormalizedColorSensor;
import com.qualcomm.robotcore.hardware.NormalizedRGBA;
import com.qualcomm.robotcore.hardware.PIDFCoefficients;
import com.qualcomm.robotcore.hardware.Servo;
import com.qualcomm.robotcore.util.ElapsedTime;

import org.firstinspires.ftc.robotcore.external.Telemetry;
import org.firstinspires.ftc.robotcore.external.navigation.DistanceUnit;

import java.util.ArrayDeque;
import java.util.Deque;

/**
 * Hardware layer for the BIOBUZZ bot built on the goBILDA 3200-2627-0004 StarterBot.
 *
 * Subsystems:
 *  - mecanum drive (four 19.2:1 Yellow Jackets),
 *  - intake: Gecko-wheel conveyor motor plus two corner servos,
 *  - launcher: 1:1 Yellow Jacket on the 96 mm Hogback wheel, windmill feeder, and the new
 *    servo-adjustable hood that opens the compression gap for NECTAR,
 *  - element sensor: colour sensor in the chute that classifies each ball as it enters.
 *
 * Everything here is loop-friendly: call {@link #update()} once per loop from an OpMode and
 * the class handles rejection timing, the four-element limit and hood selection.
 */
public class BioBuzzRobot {

    // ---- hardware ----
    private DcMotor frontLeft, frontRight, rearLeft, rearRight;
    private DcMotor intake;
    private CRServo leftIntakeServo, rightIntakeServo;
    private DcMotorEx launcher;
    private CRServo windmill;
    private Servo hood;
    private NormalizedColorSensor elementSensor;
    private DistanceSensor elementDistance;

    // ---- state ----
    private Alliance alliance = Alliance.get();
    private boolean hardwarePresent = true;
    private String missingDevice = "";

    /** Elements believed to be in the robot, oldest first, so the launcher knows what comes next. */
    private final Deque<ElementKind> stored = new ArrayDeque<>();
    private boolean elementWasPresent = false;
    private ElementKind lastSeen = ElementKind.NONE;
    private final ElapsedTime rejectTimer = new ElapsedTime();
    private boolean rejecting = false;
    private final ElapsedTime feedTimer = new ElapsedTime();
    private boolean feeding = false;
    private final ElapsedTime hoodTimer = new ElapsedTime();
    private ElementKind hoodSetFor = ElementKind.NONE;
    private double hoodTrim = 0;
    private boolean launcherOn = false;

    // values written once per loop
    private double intakePower = 0;
    private double windmillPower = 0;

    public BioBuzzRobot(HardwareMap hardwareMap) {
        frontLeft = get(hardwareMap, DcMotor.class, BioBuzzConfig.FRONT_LEFT);
        frontRight = get(hardwareMap, DcMotor.class, BioBuzzConfig.FRONT_RIGHT);
        rearLeft = get(hardwareMap, DcMotor.class, BioBuzzConfig.REAR_LEFT);
        rearRight = get(hardwareMap, DcMotor.class, BioBuzzConfig.REAR_RIGHT);
        intake = get(hardwareMap, DcMotor.class, BioBuzzConfig.INTAKE);
        leftIntakeServo = get(hardwareMap, CRServo.class, BioBuzzConfig.LEFT_INTAKE_SERVO);
        rightIntakeServo = get(hardwareMap, CRServo.class, BioBuzzConfig.RIGHT_INTAKE_SERVO);
        launcher = get(hardwareMap, DcMotorEx.class, BioBuzzConfig.LAUNCHER);
        windmill = get(hardwareMap, CRServo.class, BioBuzzConfig.WINDMILL);
        hood = get(hardwareMap, Servo.class, BioBuzzConfig.HOOD);
        elementSensor = get(hardwareMap, NormalizedColorSensor.class, BioBuzzConfig.ELEMENT_SENSOR);
        if (elementSensor instanceof DistanceSensor) {
            elementDistance = (DistanceSensor) elementSensor;
        }

        if (!hardwarePresent) {
            return;
        }

        // Same directions as goBILDA's mecanum StarterBot sample.
        frontLeft.setDirection(DcMotorSimple.Direction.REVERSE);
        rearLeft.setDirection(DcMotorSimple.Direction.REVERSE);
        frontRight.setDirection(DcMotorSimple.Direction.FORWARD);
        rearRight.setDirection(DcMotorSimple.Direction.FORWARD);
        for (DcMotor m : new DcMotor[]{frontLeft, frontRight, rearLeft, rearRight, intake}) {
            m.setZeroPowerBehavior(BRAKE);
        }

        rightIntakeServo.setDirection(DcMotorSimple.Direction.REVERSE);
        windmill.setDirection(DcMotorSimple.Direction.REVERSE);
        leftIntakeServo.setPower(0);
        rightIntakeServo.setPower(0);
        windmill.setPower(0);

        launcher.setMode(DcMotor.RunMode.RUN_USING_ENCODER);
        launcher.setPIDFCoefficients(DcMotor.RunMode.RUN_USING_ENCODER,
                new PIDFCoefficients(BioBuzzConfig.LAUNCH_P, BioBuzzConfig.LAUNCH_I,
                        BioBuzzConfig.LAUNCH_D, BioBuzzConfig.LAUNCH_F));

        elementSensor.setGain(BioBuzzConfig.SENSOR_GAIN);
        setHoodFor(ElementKind.POLLEN);
    }

    private <T> T get(HardwareMap map, Class<T> type, String name) {
        try {
            return map.get(type, name);
        } catch (IllegalArgumentException e) {
            hardwarePresent = false;
            missingDevice = missingDevice.isEmpty() ? name : missingDevice + ", " + name;
            return null;
        }
    }

    public boolean isHardwarePresent() {
        return hardwarePresent;
    }

    public String getMissingDevice() {
        return missingDevice;
    }

    // ------------------------------------------------------------------ alliance

    public void setAlliance(Alliance a) {
        alliance = a;
        Alliance.set(a);
    }

    public Alliance getAlliance() {
        return alliance;
    }

    // ------------------------------------------------------------------ drive

    /** Robot-centric mecanum drive. forward/strafe/rotate are -1..1. */
    public void drive(double forward, double strafe, double rotate) {
        double fl = forward + strafe + rotate;
        double fr = forward - strafe - rotate;
        double rl = forward - strafe + rotate;
        double rr = forward + strafe - rotate;
        double max = Math.max(1.0, Math.max(Math.max(Math.abs(fl), Math.abs(fr)),
                Math.max(Math.abs(rl), Math.abs(rr))));
        frontLeft.setPower(fl / max);
        frontRight.setPower(fr / max);
        rearLeft.setPower(rl / max);
        rearRight.setPower(rr / max);
    }

    public void stopDrive() {
        drive(0, 0, 0);
    }

    // ------------------------------------------------------------------ intake

    /**
     * Request intake power for this loop (+1 in, -1 out). The four-element limit and the
     * opponent-NECTAR rejection can override it in {@link #update()}.
     */
    public void requestIntake(double power) {
        intakePower = power;
    }

    public int getStoredCount() {
        return stored.size();
    }

    public Deque<ElementKind> getStored() {
        return stored;
    }

    /** Driver correction when the estimate drifts (for example after a jam is cleared by hand). */
    public void clearStored() {
        stored.clear();
    }

    /** Pre-load bookkeeping: four POLLEN start the match in the robot (section 10.3.1). */
    public void setPreloaded(int pollenCount) {
        stored.clear();
        for (int i = 0; i < pollenCount; i++) {
            stored.addLast(ElementKind.POLLEN);
        }
    }

    public ElementKind getLastSeen() {
        return lastSeen;
    }

    public boolean isRejecting() {
        return rejecting;
    }

    // ------------------------------------------------------------------ launcher

    /** Spin the launcher up (true) or down (false). */
    public void setLauncher(boolean on) {
        launcherOn = on;
    }

    /** The element that will be fed next, POLLEN when the queue is empty. */
    public ElementKind nextElement() {
        ElementKind next = stored.peekFirst();
        return next == null ? ElementKind.POLLEN : next;
    }

    public int targetVelocityFor(ElementKind kind) {
        return kind.isNectar() ? BioBuzzConfig.LAUNCH_VELOCITY_NECTAR : BioBuzzConfig.LAUNCH_VELOCITY_POLLEN;
    }

    public int minVelocityFor(ElementKind kind) {
        return kind.isNectar() ? BioBuzzConfig.LAUNCH_MIN_VELOCITY_NECTAR : BioBuzzConfig.LAUNCH_MIN_VELOCITY_POLLEN;
    }

    public double getLauncherVelocity() {
        return launcher.getVelocity();
    }

    /** True when the wheel is fast enough and the hood has settled for the next element. */
    public boolean readyToFeed() {
        ElementKind next = nextElement();
        boolean hoodMatches = hoodSetFor.isNectar() == next.isNectar();
        return launcherOn
                && launcher.getVelocity() >= minVelocityFor(next)
                && hoodMatches
                && hoodTimer.seconds() >= BioBuzzConfig.HOOD_SETTLE_SECONDS;
    }

    /**
     * Feed while the caller holds this true. The windmill only turns once the launcher is up to
     * speed for the element at the head of the queue, and each {@code FEED_SECONDS_PER_ELEMENT}
     * of feeding pops one element from the estimate.
     */
    public void requestFeed(boolean feed) {
        if (feed && readyToFeed()) {
            windmillPower = BioBuzzConfig.WINDMILL_FEED_POWER;
            intakePower += BioBuzzConfig.INTAKE_ASSIST_WHILE_LAUNCHING;
            if (!feeding) {
                feeding = true;
                feedTimer.reset();
            } else if (feedTimer.seconds() >= BioBuzzConfig.FEED_SECONDS_PER_ELEMENT) {
                stored.pollFirst();
                feedTimer.reset();
            }
        } else {
            windmillPower = 0;
            feeding = false;
        }
    }

    // ------------------------------------------------------------------ hood

    private void setHoodFor(ElementKind kind) {
        ElementKind normalized = kind.isNectar() ? ElementKind.NECTAR_RED : ElementKind.POLLEN;
        if (normalized != hoodSetFor) {
            hoodSetFor = normalized;
            hoodTimer.reset();
        }
        double base = normalized.isNectar() ? BioBuzzConfig.HOOD_NECTAR : BioBuzzConfig.HOOD_POLLEN;
        hood.setPosition(clamp01(base + hoodTrim));
    }

    /** Nudge the hood by one step for on-field tuning; the trim applies to both positions. */
    public void trimHood(int direction) {
        hoodTrim += direction * BioBuzzConfig.HOOD_STEP;
        setHoodFor(hoodSetFor);
    }

    public double getHoodPosition() {
        return hood.getPosition();
    }

    public double getHoodTrim() {
        return hoodTrim;
    }

    // ------------------------------------------------------------------ sensor

    /** Classify what is in front of the chute sensor right now. */
    public ElementKind sense() {
        if (elementDistance != null) {
            double mm = elementDistance.getDistance(DistanceUnit.MM);
            if (Double.isNaN(mm) || mm > BioBuzzConfig.SENSOR_PRESENT_MM) {
                return ElementKind.NONE;
            }
        }
        NormalizedRGBA rgba = elementSensor.getNormalizedColors();
        float[] hsv = new float[3];
        Color.colorToHSV(rgba.toColor(), hsv);
        float hue = hsv[0];
        float sat = hsv[1];
        if (sat < 0.3f) {
            return ElementKind.NONE;   // grey chute wall or nothing close enough
        }
        if (hue >= BioBuzzConfig.HUE_YELLOW_MIN && hue <= BioBuzzConfig.HUE_YELLOW_MAX) {
            return ElementKind.POLLEN;
        }
        if (hue >= BioBuzzConfig.HUE_BLUE_MIN && hue <= BioBuzzConfig.HUE_BLUE_MAX) {
            return ElementKind.NECTAR_BLUE;
        }
        if (hue <= BioBuzzConfig.HUE_RED_MAX || hue >= BioBuzzConfig.HUE_RED_MIN) {
            return ElementKind.NECTAR_RED;
        }
        return ElementKind.NONE;
    }

    // ------------------------------------------------------------------ per-loop update

    /**
     * Apply everything requested this loop. Call exactly once per loop, after the OpMode has
     * made its requests, so each actuator is written a single time.
     */
    public void update() {
        // 1. watch the chute: a rising edge of "element present" while intaking counts one in
        ElementKind seen = sense();
        boolean present = seen != ElementKind.NONE;
        if (present) {
            lastSeen = seen;
        }
        if (present && !elementWasPresent && intakePower > 0 && !rejecting) {
            if (seen.isLegalFor(alliance)) {
                if (stored.size() < BioBuzzConfig.MAX_ELEMENTS) {
                    stored.addLast(seen);
                }
            } else {
                rejecting = true;          // G408: opponent NECTAR, spit it back out
                rejectTimer.reset();
            }
        }
        elementWasPresent = present;

        // 2. overrides on the intake
        if (rejecting) {
            if (rejectTimer.seconds() < BioBuzzConfig.REJECT_SECONDS) {
                intakePower = -1.0;
            } else {
                rejecting = false;
            }
        } else if (intakePower > 0 && stored.size() >= BioBuzzConfig.MAX_ELEMENTS && windmillPower == 0) {
            intakePower = 0;               // G407: hold at four unless we are launching
        }

        // 3. launcher and hood follow the next element in the queue
        ElementKind next = nextElement();
        setHoodFor(next);
        launcher.setVelocity(launcherOn ? targetVelocityFor(next) : 0);

        // 4. write actuators once
        double ip = Math.max(-1, Math.min(1, intakePower));
        intake.setPower(ip);
        leftIntakeServo.setPower(ip);
        rightIntakeServo.setPower(ip);
        windmill.setPower(windmillPower);

        // reset per-loop requests
        intakePower = 0;
        windmillPower = 0;
    }

    public void stop() {
        stopDrive();
        intake.setPower(0);
        leftIntakeServo.setPower(0);
        rightIntakeServo.setPower(0);
        windmill.setPower(0);
        launcher.setVelocity(0);
    }

    public void addTelemetry(Telemetry t) {
        t.addData("Alliance", alliance);
        t.addData("Stored", "%d %s", stored.size(), stored);
        t.addData("Next", nextElement());
        t.addData("Sensor", lastSeen);
        t.addData("Launcher", "%.0f t/s (target %d), ready=%b", launcher.getVelocity(),
                launcherOn ? targetVelocityFor(nextElement()) : 0, readyToFeed());
        t.addData("Hood", "%.2f (trim %+.2f) for %s", hood.getPosition(), hoodTrim, hoodSetFor);
        if (rejecting) {
            t.addData("Intake", "REJECTING opponent NECTAR");
        }
    }

    private static double clamp01(double v) {
        return Math.max(0, Math.min(1, v));
    }
}
