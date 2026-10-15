package demo;

public class Service {
    private final Core core = new Core();

    public int covered(int value) {
        return core.twice(value) + 1;
    }

    public int uncovered(int value) {
        return core.twice(value) + 2;
    }
}
