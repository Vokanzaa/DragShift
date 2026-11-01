// Classic files.4 Melt: bridge motion vectors, without the later clean-video blend.
let index = 0;
let options;
export function setup(args) {
    args.features = ["mv"];
    options = args.params;
}
export function glitch_frame(frame) {
    const n = index++;
    const vectors = frame.mv?.forward;
    const active = options.ranges ? options.ranges.find(r => n >= r.start && n < r.end) : options;
    if (!vectors || !active || n < active.start || n >= active.end) return;
    frame.mv.overflow = "truncate";
    const cut = active.cut ?? active.start;
    const attack = n < cut ? (n - active.start) / Math.max(1, cut - active.start) : 1;
    const amount = active.strength / 100 * attack * attack * (3 - 2 * attack);
    const phase = Math.max(0, (n - cut) / Math.max(1, active.end - cut));
    const envelope = Math.sin(Math.PI * Math.min(.98, phase + .1));
    for (let y = 0; y < vectors.length; y++) {
        const row = vectors[y];
        for (let x = 0; x < row.length; x++) {
            const mv = row[x];
            const dx = mv[0] * (1 + amount * 2) + amount * 5 * envelope;
            const dy = mv[1] * (1 + amount * 2) - amount * 3 * envelope;
            mv[0] = Math.round(dx);
            mv[1] = Math.round(dy);
        }
    }
}
