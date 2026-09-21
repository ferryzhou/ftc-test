package org.firstinspires.ftc.teamcode.biobuzz;

/** What the element sensor saw. */
public enum ElementKind {
    NONE,
    POLLEN,
    NECTAR_RED,
    NECTAR_BLUE;

    public boolean isNectar() {
        return this == NECTAR_RED || this == NECTAR_BLUE;
    }

    /** True when this element may be CONTROLLED by the given alliance (G408). */
    public boolean isLegalFor(Alliance alliance) {
        if (this == POLLEN) return true;
        if (this == NECTAR_RED) return alliance == Alliance.RED;
        if (this == NECTAR_BLUE) return alliance == Alliance.BLUE;
        return false;
    }
}
