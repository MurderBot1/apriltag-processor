// Multithreaded negotiated-congestion (PathFinder) grid router for the 2-signal-layer / 2-plane board.
//   g++ -O3 -march=native -std=c++20 -pthread router.cpp -o router
//   router problem.txt solution.txt [threads] [max_seconds] [max_iters]
// Units: mm. Grid 0.05 mm, layers 0 = F.Cu, 1 = B.Cu. Moves: 8 directions + via. Weighted A* inside a growing bbox.
// Static copper is rasterised into three clearance-inflated maps (signal track, power track, via); routed copper is
// tracked as per-net "claim" footprints (atomic counts) so any number of threads can rip up / reroute concurrently.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <array>
#include <mutex>
#include <random>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
using namespace std;

static const double PITCH = 0.05;
static double W0 = 0.12;
static const double W1 = 0.30, CLR0 = 0.12, CLR1 = 0.12, VIA_D = 0.45, VIA_DR = 0.20;
static const double EDGE_CLR = 0.25;
static double HOLE_CLR = 0.25;

struct Prim { int net, mask, t, kind; double v[5]; };   // kind 0 = pad (core forbids vias), 1 = other copper, 2 = hole
struct Net { string name; int cls; };
struct Pin { int prim; int net; int mask; bool need; double cx, cy, hx, hy; vector<int> cells; };

static vector<Prim> prims;
static vector<Net> nets;
static vector<Pin> pins;
static double bx0, by0, bx1, by1, brad;
static int GW, GH, N;                 // grid size, cells per layer
static double ox, oy;                 // grid origin (mm)

static inline double dist_prim(const Prim& p, double x, double y) {
    switch (p.t) {
    case 0: { double dx = max({p.v[0] - x, 0.0, x - p.v[2]}), dy = max({p.v[1] - y, 0.0, y - p.v[3]}); return hypot(dx, dy); }
    case 1: return hypot(x - p.v[0], y - p.v[1]) - p.v[2];
    default: {
        double ax = p.v[0], ay = p.v[1], bx = p.v[2], by = p.v[3], vx = bx - ax, vy = by - ay;
        double L = vx * vx + vy * vy, t = L > 0 ? ((x - ax) * vx + (y - ay) * vy) / L : 0;
        t = min(1.0, max(0.0, t));
        return hypot(x - (ax + t * vx), y - (ay + t * vy)) - p.v[4] / 2;
    }
    }
}
static void prim_bbox(const Prim& p, double& x0, double& y0, double& x1, double& y1) {
    if (p.t == 0) { x0 = p.v[0]; y0 = p.v[1]; x1 = p.v[2]; y1 = p.v[3]; }
    else if (p.t == 1) { x0 = p.v[0] - p.v[2]; x1 = p.v[0] + p.v[2]; y0 = p.v[1] - p.v[2]; y1 = p.v[1] + p.v[2]; }
    else { double h = p.v[4] / 2; x0 = min(p.v[0], p.v[2]) - h; x1 = max(p.v[0], p.v[2]) + h; y0 = min(p.v[1], p.v[3]) - h; y1 = max(p.v[1], p.v[3]) + h; }
}
static double edge_dist(double x, double y) {            // distance from (x,y) to the board outline, positive inside
    double cx0 = bx0 + brad, cx1 = bx1 - brad, cy0 = by0 + brad, cy1 = by1 - brad;
    double qx = max({cx0 - x, 0.0, x - cx1}), qy = max({cy0 - y, 0.0, y - cy1});
    if (qx > 0 || qy > 0) return brad - hypot(qx, qy);
    return min({x - bx0, bx1 - x, y - by0, by1 - y});
}

// ---- static maps: -1 free, -2 blocked, >= 0 owner net
struct Maps { vector<int16_t> m[3][2]; } SM;          // [0] signal track, [1] power track, [2] via
static void merge_cell(int16_t& c, int owner) { if (c == -1) c = (int16_t)owner; else if (c != owner) c = -2; }

static void build_static() {
    for (int k = 0; k < 3; k++) for (int l = 0; l < 2; l++) SM.m[k][l].assign(N, -1);
    // board edge
    const double em[3] = {EDGE_CLR + W0 / 2, EDGE_CLR + W1 / 2, EDGE_CLR + VIA_D / 2};
    for (int y = 0; y < GH; y++) for (int x = 0; x < GW; x++) {
        double px = ox + x * PITCH, py = oy + y * PITCH, d = edge_dist(px, py);
        for (int k = 0; k < 3; k++) if (d < em[k]) for (int l = 0; l < 2; l++) SM.m[k][l][y * GW + x] = -2;
    }
    const double VC = max(max(CLR0, CLR1), HOLE_CLR + VIA_DR / 2 - VIA_D / 2);   // via vs copper: clearance or drill-hole rule
    const double cm[3] = {CLR0 + W0 / 2, CLR1 + W1 / 2, VC + VIA_D / 2};
    const double hm[3] = {HOLE_CLR + W0 / 2, HOLE_CLR + W1 / 2, HOLE_CLR + VIA_D / 2 + 0.0};
    for (int pass = 0; pass < 2; pass++) {
        for (auto& p : prims) {
            bool pad = p.kind == 0;
            if (pass == 1 && !pad) continue;
            double x0, y0, x1, y1; prim_bbox(p, x0, y0, x1, y1);
            int owner = p.net >= 0 ? p.net : -2;
            for (int k = 0; k < 3; k++) {
                double mg = p.kind == 2 ? hm[k] : cm[k];
                int cx0 = max(0, (int)floor((x0 - mg - ox) / PITCH)), cx1 = min(GW - 1, (int)ceil((x1 + mg - ox) / PITCH));
                int cy0 = max(0, (int)floor((y0 - mg - oy) / PITCH)), cy1 = min(GH - 1, (int)ceil((y1 + mg - oy) / PITCH));
                for (int y = cy0; y <= cy1; y++) for (int x = cx0; x <= cx1; x++) {
                    double d = dist_prim(p, ox + x * PITCH, oy + y * PITCH);
                    for (int l = 0; l < 2; l++) {
                        if (!(p.mask >> l & 1)) continue;
                        int16_t& c = SM.m[k][l][y * GW + x];
                        if (pass == 0) { if (d <= mg) merge_cell(c, (p.kind == 2 || (k == 2 && p.t == 1 && p.kind == 1 && p.mask == 3)) ? -2 : owner); }
                        else if (d <= 0) c = (k == 2) ? -2 : (int16_t)owner;
                    }
                }
            }
        }
    }
}

// ---- dynamic claims
static vector<int16_t> CLA[4][2];                     // claim counts per query kind q (0 sig-track,1 sig-via,2 pow-track,3 pow-via) and layer
static vector<float> HIST[2];
static inline int16_t ld(vector<int16_t>& v, int i) { return atomic_ref<int16_t>(v[i]).load(memory_order_relaxed); }
static inline void addc(vector<int16_t>& v, int i, int d) { atomic_ref<int16_t>(v[i]).fetch_add(d, memory_order_relaxed); }

struct Disk { vector<pair<int, int>> off; };
static Disk disk(double r) { Disk d; int R = (int)ceil(r / PITCH); for (int y = -R; y <= R; y++) for (int x = -R; x <= R; x++) if (hypot(x * PITCH, y * PITCH) <= r + 1e-9) d.off.push_back({x, y}); return d; }
static Disk DK[2][4], DV[2][4];   // [job class][query kind]: footprint of a track cell / of a via

struct Seg { int l, x0, y0, x1, y1; };
struct Via { int x, y; };
struct Job {
    int net, cls; bool plane; vector<int> pins;    // pin indices (all for a signal net; one for a plane pad)
    vector<Seg> segs; vector<Via> vias; vector<int> cl_ids;          // routed geometry + centreline node ids
    vector<int> fp[4];                                             // footprint cells (layer*N + cell) per query kind, deduplicated
    bool routed = false, dirty = true, frozen = false;
    int hpwl = 0;
    int bx0 = 0, by0 = 0, bx1 = 0, by1 = 0;           // cell bbox (pins + last route) used to batch non-overlapping reroutes
};
static vector<Job> jobs;
static atomic<long> g_expanded{0};

struct Scratch {
    vector<float> g; vector<uint32_t> gen_open, gen_closed, fstamp[4], goal; vector<int> parent; vector<int8_t> pdir;
    vector<pair<float, int>> heap; vector<int> myvias; uint32_t gen = 0, fgen = 0, ggen = 0;
    void init() {
        size_t M = 2 * (size_t)N; g.assign(M, 0); gen_open.assign(M, 0); gen_closed.assign(M, 0); for (auto& f : fstamp) f.assign(M, 0); goal.assign(M, 0); parent.assign(M, -1); pdir.assign(M, 0);
        heap.reserve(1 << 20);
    }
};

static const int DX[8] = {1, 1, 0, -1, -1, -1, 0, 1}, DY[8] = {0, 1, 1, 1, 0, -1, -1, -1};
static float VIA_COST = 18.0f;
static float PFMAX = 6.f, HINC = 1.5f, HGROW = 0.f;

static inline bool pass_static(int cls, int l, int c, int net) {
    int16_t s = SM.m[cls][l][c]; return s == -1 || s == net;
}
static inline bool via_ok(int c, int net) {
    int16_t a = SM.m[2][0][c], b = SM.m[2][1][c];
    return (a == -1 || a == net) && (b == -1 || b == net);
}

static void ripup(Job& j) {
    for (int q = 0; q < 4; q++) { for (int id : j.fp[q]) addc(CLA[q][id / N], id % N, -1); j.fp[q].clear(); }
    j.segs.clear(); j.vias.clear(); j.cl_ids.clear(); j.routed = false;
}
static void commit(Job& j, Scratch& s, const vector<int>& nodes_cl, const vector<int>& via_cells) {
    s.fgen++;
    int cls = j.cls == 1 ? 1 : 0;
    auto put = [&](const Disk& d, int cx, int cy, int l, int q) {
        for (auto& o : d.off) {
            int x = cx + o.first, y = cy + o.second; if (x < 0 || y < 0 || x >= GW || y >= GH) continue;
            int id = l * N + y * GW + x; if (s.fstamp[q][id] == s.fgen) continue; s.fstamp[q][id] = s.fgen; j.fp[q].push_back(id); addc(CLA[q][l], y * GW + x, 1);
        }
    };
    for (int id : nodes_cl) { int l = id / N, c = id % N; for (int q = 0; q < 4; q++) put(DK[cls][q], c % GW, c / GW, l, q); }
    for (int c : via_cells) for (int l = 0; l < 2; l++) for (int q = 0; q < 4; q++) put(DV[cls][q], c % GW, c / GW, l, q);
}

// A*. sources: node ids with g=0. goal: nodes stamped with s.goal==s.ggen, or plane mode (any legal via site).
// Returns the goal node id or -1; path via parent[].
static int astar(Job& j, Scratch& s, const vector<int>& sources, double tcx, double tcy, double thx, double thy,
                 bool plane, int bxa, int bya, int bxb, int byb, float pf) {
    s.gen++; s.heap.clear();
    int net = j.net, cls = j.cls == 1 ? 1 : 0, qt = cls * 2, qv = qt + 1;
    const float W = 1.15f;
    auto h = [&](int c) -> float {
        if (plane) return 0.f;
        double dx = fabs((c % GW) - tcx) - thx, dy = fabs((c / GW) - tcy) - thy; dx = max(0.0, dx); dy = max(0.0, dy);
        double mn = min(dx, dy), mx = max(dx, dy); return (float)((mx - mn) + 1.41421356 * mn) * W;
    };
    auto push = [&](int id, float gv, int par, int8_t dir) {
        s.g[id] = gv; s.gen_open[id] = s.gen; s.parent[id] = par; s.pdir[id] = dir;
        s.heap.push_back({gv + h(id % N), id}); push_heap(s.heap.begin(), s.heap.end(), greater<>());
    };
    for (int id : sources) push(id, 0.f, -1, 8);
    while (!s.heap.empty()) {
        pop_heap(s.heap.begin(), s.heap.end(), greater<>()); auto [f, id] = s.heap.back(); s.heap.pop_back();
        if (s.gen_closed[id] == s.gen) continue;
        s.gen_closed[id] = s.gen;
        int l = id / N, c = id % N, x = c % GW, y = c / GW;
        float gc = s.g[id];
        g_expanded.fetch_add(1, memory_order_relaxed);
        if (plane) { if (s.parent[id] >= 0 || true) { if (via_ok(c, net) && ld(CLA[qv][0], c) == 0 && ld(CLA[qv][1], c) == 0 && gc > 0) return id; } }
        else if (s.goal[id] == s.ggen) return id;
        int8_t pd = s.pdir[id];
        for (int d = 0; d < 8; d++) {
            int nx = x + DX[d], ny = y + DY[d];
            if (nx < bxa || nx > bxb || ny < bya || ny > byb) continue;
            int nc = ny * GW + nx, nid = l * N + nc;
            if (s.gen_closed[nid] == s.gen) continue;
            if (!pass_static(cls, l, nc, net)) continue;
            if (d & 1) { if (!pass_static(cls, l, y * GW + nx, net) || !pass_static(cls, l, ny * GW + x, net)) continue; }
            float step = (d & 1) ? 1.41421356f : 1.f;
            if (!(d & 1)) { if ((l == 0 && (d & 1) == 0 && DY[d] != 0) || (l == 1 && DX[d] != 0)) step *= 1.35f; }
            int cn = ld(CLA[qt][l], nc);
            float cost = step * (1.f + pf * cn) + HIST[l][nc];
            if (pd != 8 && pd != d) { int df = abs(pd - d); df = min(df, 8 - df); cost += df == 1 ? 0.5f : (df == 2 ? 1.5f : 3.f); }
            float ng = gc + cost;
            if (s.gen_open[nid] == s.gen && s.g[nid] <= ng) continue;
            push(nid, ng, id, (int8_t)d);
        }
        // via
        bool near_own = false;
        for (int vc : s.myvias) { int dx = vc % GW - x, dy = vc / GW - y; if (dx * dx + dy * dy < 133) { near_own = true; break; } }
        if (!near_own && via_ok(c, net) && pass_static(cls, 1 - l, c, net)) {
            int nid = (1 - l) * N + c;
            if (s.gen_closed[nid] != s.gen) {
                int cv = ld(CLA[qv][0], c) + ld(CLA[qv][1], c);
                float ng = gc + VIA_COST * (1.f + pf * cv * 0.5f) + HIST[l][c] + HIST[1 - l][c];
                if (!(s.gen_open[nid] == s.gen && s.g[nid] <= ng)) push(nid, ng, id, 8);
            }
        }
    }
    return -1;
}

// turn a node chain (goal -> source) into segments/vias; returns centreline node ids and via cells
static void trace(Job& j, Scratch& s, int goal, vector<int>& cl, vector<int>& vcells) {
    vector<int> chain; for (int id = goal; id >= 0; id = s.parent[id]) chain.push_back(id);
    reverse(chain.begin(), chain.end());
    for (size_t i = 0; i < chain.size(); i++) {
        cl.push_back(chain[i]);
        if (i && chain[i] / N != chain[i - 1] / N) vcells.push_back(chain[i] % N);
    }
    // segments: merge collinear runs
    size_t i = 0;
    while (i + 1 < chain.size()) {
        int l = chain[i] / N;
        if (chain[i + 1] / N != l) { i++; continue; }
        int c0 = chain[i] % N, c1 = chain[i + 1] % N;
        int dx = (c1 % GW) - (c0 % GW), dy = (c1 / GW) - (c0 / GW);
        size_t k = i + 1;
        while (k + 1 < chain.size() && chain[k + 1] / N == l) {
            int a = chain[k] % N, b = chain[k + 1] % N;
            if ((b % GW) - (a % GW) == dx && (b / GW) - (a / GW) == dy) k++; else break;
        }
        int ce = chain[k] % N;
        j.segs.push_back({l, c0 % GW, c0 / GW, ce % GW, ce / GW});
        i = k;
    }
    for (int c : vcells) j.vias.push_back({c % GW, c / GW});
}

static bool route_job(Job& j, Scratch& s, float pf, double& ms_unused) {
    ripup(j); s.myvias.clear();
    vector<int> cl_all, via_all;
    int cls = j.cls == 1 ? 1 : 0;
    (void)cls;
    if (j.plane) {
        Pin& p = pins[j.pins[0]];
        vector<int> src; for (int l = 0; l < 2; l++) if (p.mask >> l & 1) for (int c : p.cells) src.push_back(l * N + c);
        int px = (int)round((p.cx - ox) / PITCH), py = (int)round((p.cy - oy) / PITCH);
        for (int m = 30;; m *= 2) {
            int bxa = max(0, px - m), bya = max(0, py - m), bxb = min(GW - 1, px + m), byb = min(GH - 1, py + m);
            int g = astar(j, s, src, 0, 0, 0, 0, true, bxa, bya, bxb, byb, pf);
            if (g >= 0) { trace(j, s, g, cl_all, via_all); via_all.push_back(g % N); j.vias.push_back({(g % N) % GW, (g % N) / GW}); commit(j, s, cl_all, via_all); j.cl_ids = cl_all; j.routed = true; return true; }
            if (m > GW + GH) break;
        }
        return false;
    }
    // signal / power net: Prim order over pins
    vector<int> order; vector<char> done(j.pins.size(), 0);
    vector<int> tree;
    auto addpin = [&](int k) { Pin& p = pins[j.pins[k]]; done[k] = 1; for (int l = 0; l < 2; l++) if (p.mask >> l & 1) for (int c : p.cells) tree.push_back(l * N + c); };
    addpin(0);
    vector<int> connected_idx{0};
    bool ok = true;
    for (size_t it = 1; it < j.pins.size(); it++) {
        int best = -1; double bd = 1e18;
        for (size_t k = 0; k < j.pins.size(); k++) if (!done[k]) {
            Pin& p = pins[j.pins[k]];
            for (int ci : connected_idx) { Pin& q = pins[j.pins[ci]]; double d = hypot(p.cx - q.cx, p.cy - q.cy); if (d < bd) { bd = d; best = k; } }
        }
        Pin& t = pins[j.pins[best]];
        s.ggen++;
        for (int l = 0; l < 2; l++) if (t.mask >> l & 1) for (int c : t.cells) s.goal[l * N + c] = s.ggen;
        double tcx = (t.cx - ox) / PITCH, tcy = (t.cy - oy) / PITCH, thx = t.hx / PITCH, thy = t.hy / PITCH;
        double minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
        for (int ci : connected_idx) { Pin& q = pins[j.pins[ci]]; minx = min(minx, q.cx); maxx = max(maxx, q.cx); miny = min(miny, q.cy); maxy = max(maxy, q.cy); }
        minx = min(minx, t.cx); maxx = max(maxx, t.cx); miny = min(miny, t.cy); maxy = max(maxy, t.cy);
        int g = -1;
        for (int m = 40;; m *= 2) {
            int bxa = max(0, (int)floor((minx - ox) / PITCH) - m), bya = max(0, (int)floor((miny - oy) / PITCH) - m);
            int bxb = min(GW - 1, (int)ceil((maxx - ox) / PITCH) + m), byb = min(GH - 1, (int)ceil((maxy - oy) / PITCH) + m);
            g = astar(j, s, tree, tcx, tcy, thx, thy, false, bxa, bya, bxb, byb, pf);
            if (g >= 0 || m > GW + GH) break;
        }
        if (g < 0) { ok = false; break; }
        vector<int> cl, vc; trace(j, s, g, cl, vc);
        for (int id : cl) { tree.push_back(id); cl_all.push_back(id); }
        for (int c : vc) { via_all.push_back(c); s.myvias.push_back(c); }
        for (int l = 0; l < 2; l++) if (t.mask >> l & 1) for (int c : t.cells) tree.push_back(l * N + c);
        done[best] = 1; connected_idx.push_back(best);
    }
    commit(j, s, cl_all, via_all); j.cl_ids = cl_all; j.routed = ok;
    return ok;
}

static void parse(const string& fn) {
    ifstream f(fn); string ln; vector<array<double, 9>> raw;
    while (getline(f, ln)) {
        istringstream is(ln); string tag; is >> tag;
        if (tag == "B") is >> bx0 >> by0 >> bx1 >> by1 >> brad;
        else if (tag == "N") { int id, cls; string nm; is >> id >> cls >> nm; if ((int)nets.size() <= id) nets.resize(id + 1); nets[id] = {nm, cls}; }
        else if (tag == "H") { Prim p{-1, 3, 1, 2, {0, 0, 0, 0, 0}}; is >> p.v[0] >> p.v[1] >> p.v[2]; prims.push_back(p); }
        else if (tag == "C") { Prim p; p.kind = 1; is >> p.net >> p.mask >> p.t; for (int i = 0; i < 5; i++) is >> p.v[i]; prims.push_back(p); }
        else if (tag == "P") {
            Prim p; p.kind = 0; int need; is >> p.net >> p.mask >> need >> p.t; for (int i = 0; i < 5; i++) is >> p.v[i];
            prims.push_back(p);
            Pin pn; pn.prim = (int)prims.size() - 1; pn.net = p.net; pn.mask = p.mask; pn.need = need;
            double x0, y0, x1, y1; prim_bbox(p, x0, y0, x1, y1); pn.cx = (x0 + x1) / 2; pn.cy = (y0 + y1) / 2; pn.hx = (x1 - x0) / 2; pn.hy = (y1 - y0) / 2;
            pins.push_back(pn);
        }
    }
}

int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: router problem solution [threads] [max_seconds] [max_iters]\n"); return 2; }
    int T = argc > 3 ? atoi(argv[3]) : (int)thread::hardware_concurrency();
    double tmax = argc > 4 ? atof(argv[4]) : 900; int itmax = argc > 5 ? atoi(argv[5]) : 80;
    auto t0 = chrono::steady_clock::now();
    auto el = [&] { return chrono::duration<double>(chrono::steady_clock::now() - t0).count(); };
    if (getenv("W0")) W0 = atof(getenv("W0"));
    if (getenv("HOLE")) HOLE_CLR = atof(getenv("HOLE"));
    parse(argv[1]);
    // grid aligned to the pad grid of the densest part: use the pad with the smallest pitch neighbourhood -> first circular pad
    ox = bx0; oy = by0;
    {   // align the grid with the most common circular-pad centre (the BGA ball grid)
        map<pair<int, int>, int> hist;
        for (auto& p : prims) if (p.kind == 0 && p.t == 1) hist[{(int)lround(fmod(p.v[0] - bx0 + 100, PITCH) * 1000), (int)lround(fmod(p.v[1] - by0 + 100, PITCH) * 1000)}]++;
        int best = -1; pair<int, int> bk{0, 0}; for (auto& kv : hist) if (kv.second > best) { best = kv.second; bk = kv.first; }
        ox = bx0 + bk.first / 1000.0; oy = by0 + bk.second / 1000.0;
        fprintf(stderr, "grid offset %.3f %.3f (%d pads)\n", ox - bx0, oy - by0, best);
    }
    GW = (int)floor((bx1 - ox) / PITCH) + 1; GH = (int)floor((by1 - oy) / PITCH) + 1; N = GW * GH;
    fprintf(stderr, "grid %d x %d, %zu primitives, %zu pins, %d threads\n", GW, GH, prims.size(), pins.size(), T);
    build_static();
    fprintf(stderr, "static maps built %.1fs\n", el());
    // pin cells
    for (auto& pn : pins) {
        Prim& p = prims[pn.prim]; double x0, y0, x1, y1; prim_bbox(p, x0, y0, x1, y1);
        int cx0 = max(0, (int)floor((x0 - ox) / PITCH)), cx1 = min(GW - 1, (int)ceil((x1 - ox) / PITCH));
        int cy0 = max(0, (int)floor((y0 - oy) / PITCH)), cy1 = min(GH - 1, (int)ceil((y1 - oy) / PITCH));
        for (int y = cy0; y <= cy1; y++) for (int x = cx0; x <= cx1; x++) if (dist_prim(p, ox + x * PITCH, oy + y * PITCH) <= 0) pn.cells.push_back(y * GW + x);
        if (pn.cells.empty()) pn.cells.push_back((int)round((pn.cy - oy) / PITCH) * GW + (int)round((pn.cx - ox) / PITCH));
    }
    // jobs
    vector<vector<int>> bynet(nets.size());
    for (size_t i = 0; i < pins.size(); i++) if (pins[i].net >= 0) bynet[pins[i].net].push_back((int)i);
    for (size_t n = 0; n < nets.size(); n++) {
        if (nets[n].cls == 2) { for (int pi : bynet[n]) if (pins[pi].need) { Job j; j.net = (int)n; j.cls = 0; j.plane = true; j.pins = {pi}; jobs.push_back(j); } }
        else if (bynet[n].size() >= 2) {
            Job j; j.net = (int)n; j.cls = nets[n].cls; j.plane = false; j.pins = bynet[n];
            double mnx = 1e9, mny = 1e9, mxx = -1e9, mxy = -1e9; for (int pi : j.pins) { mnx = min(mnx, pins[pi].cx); mxx = max(mxx, pins[pi].cx); mny = min(mny, pins[pi].cy); mxy = max(mxy, pins[pi].cy); }
            j.hpwl = (int)((mxx - mnx) + (mxy - mny)); jobs.push_back(j);
        }
    }
    fprintf(stderr, "%zu jobs\n", jobs.size());
    // disks: track level / via level, signal and power
    {
        const double h0 = W0 / 2, h1 = W1 / 2, vr = VIA_D / 2, cx = max(CLR0, CLR1);
        const double vc = max(cx, HOLE_CLR + VIA_DR / 2 - vr);       // via-to-copper clearance incl. the 0.25 mm drill-hole rule
        const double tk[2][4] = {{CLR0 + h0 + h0, vc + h0 + vr, cx + h1 + h0, vc + vr + h0},
                                 {cx + h1 + h0, vc + h1 + vr, CLR1 + h1 + h1, vc + h1 + vr}};
        const double vk[2][4] = {{vc + vr + h0, cx + VIA_D, vc + h1 + vr, cx + VIA_D},
                                 {vc + vr + h0, cx + VIA_D, vc + h1 + vr, cx + VIA_D}};
        for (int c = 0; c < 2; c++) for (int q = 0; q < 4; q++) { DK[c][q] = disk(tk[c][q]); DV[c][q] = disk(vk[c][q]); }
    }
    for (int l = 0; l < 2; l++) { for (int q = 0; q < 4; q++) CLA[q][l].assign(N, 0); HIST[l].assign(N, 0.f); }
    vector<Scratch> scr(T);
    { vector<thread> th; for (int i = 0; i < T; i++) th.emplace_back([&, i] { scr[i].init(); }); for (auto& t : th) t.join(); }
    fprintf(stderr, "scratch ready %.1fs\n", el());

    // order: power first (frozen after phase 1), then long nets first
    vector<int> power, rest;
    for (size_t i = 0; i < jobs.size(); i++) rest.push_back((int)i);
    auto run_batch = [&](const vector<int>& set, float pf) {
        atomic<size_t> next{0};
        vector<thread> th;
        for (int i = 0; i < T; i++) th.emplace_back([&, i] {
            double u; for (;;) { size_t k = next.fetch_add(1); if (k >= set.size()) break; route_job(jobs[set[k]], scr[i], pf, u); }
        });
        for (auto& t : th) t.join();
    };
    auto jbox = [&](Job& j) {
        int x0 = GW, y0 = GH, x1 = 0, y1 = 0;
        for (int pi : j.pins) { Pin& p = pins[pi]; int cx = (int)((p.cx - ox) / PITCH), cy = (int)((p.cy - oy) / PITCH); x0 = min(x0, cx); x1 = max(x1, cx); y0 = min(y0, cy); y1 = max(y1, cy); }
        for (int id : j.cl_ids) { int c = id % N; x0 = min(x0, c % GW); x1 = max(x1, c % GW); y0 = min(y0, c / GW); y1 = max(y1, c / GW); }
        const int m = 14;                                       // 0.7 mm: clearance footprint reach
        j.bx0 = x0 - m; j.by0 = y0 - m; j.bx1 = x1 + m; j.by1 = y1 + m;
    };
    // jobs whose boxes overlap never run concurrently, so two nets cannot both pick the same corridor in one step
    auto run_set = [&](vector<int>& set, float pf) {
        vector<int> left = set;
        while (!left.empty()) {
            vector<int> batch, rest2;
            for (int ji : left) {
                jbox(jobs[ji]); bool clash = false;
                for (int bj : batch) { Job &a = jobs[ji], &b = jobs[bj]; if (a.bx0 <= b.bx1 && b.bx0 <= a.bx1 && a.by0 <= b.by1 && b.by0 <= a.by1) { clash = true; break; } }
                (clash ? rest2 : batch).push_back(ji);
            }
            run_batch(batch, pf);
            left.swap(rest2);
        }
    };
    auto violations = [&](const vector<int>& set, bool mark) {
        long v = 0;
        for (int ji : set) {
            Job& j = jobs[ji]; bool bad = !j.routed;
            if (bad) v++;
            for (int id : j.cl_ids) {
                int l = id / N, c = id % N;
                if (ld(CLA[j.cls == 1 ? 2 : 0][l], c) > 1) { if (mark) { HIST[l][c] += HINC; } bad = true; v++; }
            }
            for (auto& vi : j.vias) {
                int c = vi.y * GW + vi.x;
                int qv = j.cls == 1 ? 3 : 1; if (ld(CLA[qv][0], c) > 1 || ld(CLA[qv][1], c) > 1) { if (mark) { HIST[0][c] += HINC; HIST[1][c] += HINC; } bad = true; v++; }
            }
            if (mark) j.dirty = bad;
        }
        return v;
    };
    sort(rest.begin(), rest.end(), [&](int a, int b) { return jobs[a].hpwl > jobs[b].hpwl; });
    if (getenv("PFMAX")) PFMAX = atof(getenv("PFMAX")); if (getenv("HINC")) HINC = atof(getenv("HINC")); if (getenv("HGROW")) HGROW = atof(getenv("HGROW"));
    if (getenv("VIA_COST")) VIA_COST = atof(getenv("VIA_COST"));
    float pf = 0.4f;
    // phase 1: power nets
    for (int it = 0; it < 12 && !power.empty(); it++) {
        vector<int> todo; for (int ji : power) if (jobs[ji].dirty) todo.push_back(ji);
        if (todo.empty()) break;
        run_set(todo, pf); long v = violations(power, true); fprintf(stderr, "power iter %d: viol %ld  %.1fs\n", it, v, el()); if (!v) break; pf *= 1.6f;
    }
    for (int ji : power) jobs[ji].frozen = true;
    // phase 2: everything else, negotiated
    pf = 0.4f;
    mt19937 rng(getenv("SEED") ? atoi(getenv("SEED")) : 1);
    vector<int> all = rest;
    for (int it = 0; it < itmax; it++) {
        vector<int> todo; for (int ji : rest) if (jobs[ji].dirty) todo.push_back(ji);
        if (todo.empty()) break;
        shuffle(todo.begin(), todo.end(), rng);
        stable_sort(todo.begin(), todo.end(), [&](int a, int b) { return jobs[a].hpwl > jobs[b].hpwl; });
        long e0 = g_expanded.load();
        run_set(todo, pf);
        long v = violations(rest, true);
        long unr = 0; for (int ji : rest) if (!jobs[ji].routed) unr++;
        // power conflicts: mark violators among signals only (power frozen) -> already via claim overlap
        long dirty = 0; for (int ji : rest) dirty += jobs[ji].dirty;
        fprintf(stderr, "iter %d: rerouted %zu, dirty %ld, viol %ld, unrouted %ld, pf %.2f, expanded %ldk, %.1fs\n", it, todo.size(), dirty, v, unr, pf, (g_expanded.load() - e0) / 1000, el());
        if (!v) break;
        HINC += HGROW;
        pf = min(pf * 1.3f, PFMAX);
        if (el() > tmax) { fprintf(stderr, "time limit\n"); break; }
    }
    // serial polish: remaining conflicts are rerouted one net at a time (no concurrent choices), cheapest-first
    {
        int pol = getenv("POLISH") ? atoi(getenv("POLISH")) : 60;
        for (int it = 0; it < pol && el() < tmax * 1.5; it++) {
            vector<int> todo; for (int ji : rest) if (jobs[ji].dirty) todo.push_back(ji);
            if (todo.empty()) break;
            shuffle(todo.begin(), todo.end(), rng);
            for (int ji : todo) { double u; route_job(jobs[ji], scr[0], pf, u); }
            long v = violations(rest, true);
            if (it % 5 == 0) fprintf(stderr, "polish %d: viol %ld dirty %zu %.1fs\n", it, v, todo.size(), el());
            if (!v) break;
        }
    }
    // output
    {   // worst offenders
        vector<pair<int, int>> w;
        for (int ji : rest) { int c = 0, qq = jobs[ji].cls == 1 ? 2 : 0; for (int id : jobs[ji].cl_ids) if (ld(CLA[qq][id / N], id % N) > 1) c++; if (c) w.push_back({c, ji}); }
        sort(w.rbegin(), w.rend());
        for (size_t i = 0; i < w.size() && i < 12; i++) {
            Job& j = jobs[w[i].second]; int fx = -1, fy = -1;
            int qq = j.cls == 1 ? 2 : 0; for (int id : j.cl_ids) if (ld(CLA[qq][id / N], id % N) > 1) { fx = (id % N) % GW; fy = (id % N) / GW; break; }
            fprintf(stderr, "  viol %d  net %s (plane=%d) at %.2f,%.2f\n", w[i].first, nets[j.net].name.c_str(), j.plane, ox + fx * PITCH, oy + fy * PITCH);
            if (fx >= 0) { int fid = -1; for (int id : j.cl_ids) if (ld(CLA[qq][id / N], id % N) > 1) { fid = id; break; }
                string who; for (auto& o : jobs) if (&o != &j) for (int id : o.fp[qq]) if (id == fid) { who += nets[o.net].name + (o.frozen ? "(F) " : " "); break; }
                int sm = SM.m[0][fid / N][fid % N]; fprintf(stderr, "     layer %d static %d claimed also by: %s\n", fid / N, sm, who.c_str()); }
        }
    }
    long v = violations(all, false), unr = 0;
    for (auto& j : jobs) if (!j.routed) unr++;
    for (int ji : power) { Job& j = jobs[ji]; if (!j.routed) unr++; }
    FILE* fo = fopen(argv[2], "w");
    long nseg = 0, nvia = 0;
    for (auto& j : jobs) {
        const string& nm = nets[j.net].name; double w = j.cls == 1 ? W1 : W0;
        for (auto& s : j.segs) { fprintf(fo, "T %s %d %.4f %.4f %.4f %.4f %.3f\n", nm.c_str(), s.l, ox + s.x0 * PITCH, oy + s.y0 * PITCH, ox + s.x1 * PITCH, oy + s.y1 * PITCH, w); nseg++; }
        for (auto& vi : j.vias) { fprintf(fo, "V %s %.4f %.4f\n", nm.c_str(), ox + vi.x * PITCH, oy + vi.y * PITCH); nvia++; }
        if (!j.routed) fprintf(fo, "U %s\n", nm.c_str());
    }
    fclose(fo);
    long unrP = 0; for (int ji : power) if (!jobs[ji].routed) unrP++;
    fprintf(stderr, "DONE %.1fs: %ld segments, %ld vias, unrouted jobs %ld (of %zu), remaining violations (signals) %ld\n", el(), nseg, nvia, unr, jobs.size(), v);
    return 0;
}
