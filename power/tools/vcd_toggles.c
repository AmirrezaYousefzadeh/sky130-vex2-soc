/* vcd_toggles: streaming per-signal toggle counts and high times from a VCD (file or pipe), with the counting rules of
 * OpenSTA's read_power_activities (power/VcdReader.cc, 2.6.0): the initial value does not count; a value change counts
 * one transition, or 0.5 when x/z is involved; high time accumulates while the value is '1'; the interval ends at the last
 * timestamp of the file. Output: one line per bit "<scope/path>\t<transitions>\t<high_time>[\t<bit>]" (bus bits carry the bit index in a 4th column),
 * header lines "#timescale_s", "#time_min", "#time_max", "#vars", "#aliases". Aliased ids (one net, several scopes) are
 * written once per alias. Round 5 of the BCI paper (E4/E7): full test blocks are accumulated without storing the waveform.
 * Build: cc -O2 -o tools/vcd_toggles sim/vcd_toggles.c      Usage: vcd_toggles [-o out.tsv] [--begin T] [--end T] [vcd | -]
 * --begin/--end: count only within [T_begin, T_end] (VCD time units), as OpenSTA read_power_activities -begin/-end do.
 * Round 10 (state-dependent power with a stopped clock): --gate <scope/path of a 1-bit variable> -g <gated.tsv> writes a second
 * table whose high times count only while the gate variable is '1' (e.g. the clock enable of the core), with the header line
 * "#gate_high" = total time the gate was '1' (VCD units): duty conditioned on the clock running = high_gated / gate_high. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>

typedef struct { char *name; int width; int msb; int lsb; int has_range; int var_index; } Alias;   /* one $var line */
typedef struct {                       /* one VCD id, possibly several aliases, width bits */
  uint64_t key; int width; int n_alias; Alias *alias;
  char *prev; long long *prev_t; double *tc; unsigned long long *high; int first;   /* per bit */
  unsigned long long *highg, *gprev;   /* round 10: high time while the gate is '1', and the cumulative gate-high time at the last change */
} Sig;

static Sig *sigs; static size_t nsig, capsig;
static uint32_t *htab; static size_t hcap;     /* open addressing: htab[h] = sig index + 1 */
static long long tmin = -1, tmax = 0, tcur = 0; static double tscale = 1e-9;
static long long wbeg = -1, wend = -1;          /* optional window [wbeg, wend] in VCD time units; -1 = unbounded */
static char scope[64][256]; static int depth;
static const char *gate_name = NULL; static Sig *gate_sig = NULL; static int gate_on = 0; static long long gate_t0 = 0; static unsigned long long gate_cum = 0;
static inline unsigned long long G(long long t) { return gate_cum + ((gate_on && t > gate_t0) ? (unsigned long long)(t - gate_t0) : 0ULL); }

static uint64_t idkey(const char *s, size_t n) { uint64_t k = 0; if (n > 8) { fprintf(stderr, "id too long: %.*s\n", (int)n, s); exit(1); } memcpy(&k, s, n); return k ^ ((uint64_t)n << 56); }
static uint64_t hsh(uint64_t k) { k ^= k >> 33; k *= 0xff51afd7ed558ccdULL; k ^= k >> 33; k *= 0xc4ceb9fe1a85ec53ULL; k ^= k >> 33; return k; }
static void hgrow(void) {
  size_t nc = hcap ? hcap * 2 : 1 << 16; uint32_t *nt = calloc(nc, sizeof *nt);
  for (size_t i = 0; i < nsig; i++) { size_t h = hsh(sigs[i].key) & (nc - 1); while (nt[h]) h = (h + 1) & (nc - 1); nt[h] = (uint32_t)i + 1; }
  free(htab); htab = nt; hcap = nc;
}
static Sig *find(uint64_t key, int create) {
  if (hcap == 0 || nsig * 2 >= hcap) hgrow();
  size_t h = hsh(key) & (hcap - 1);
  while (htab[h]) { Sig *s = &sigs[htab[h] - 1]; if (s->key == key) return s; h = (h + 1) & (hcap - 1); }
  if (!create) return NULL;
  if (nsig == capsig) { capsig = capsig ? capsig * 2 : 4096; sigs = realloc(sigs, capsig * sizeof *sigs); hgrow(); h = hsh(key) & (hcap - 1); while (htab[h]) h = (h + 1) & (hcap - 1); }
  Sig *s = &sigs[nsig]; memset(s, 0, sizeof *s); s->key = key; s->first = 1; htab[h] = (uint32_t)nsig + 1; nsig++; return s;
}
static void alloc_bits(Sig *s, int width) {
  if (s->width) return;
  s->width = width;
  s->prev = malloc(width); memset(s->prev, 0, width); s->prev_t = malloc(width * sizeof(long long));
  for (int i = 0; i < width; i++) s->prev_t[i] = -1;
  s->tc = calloc(width, sizeof(double)); s->high = calloc(width, sizeof(unsigned long long));
  s->highg = calloc(width, sizeof(unsigned long long)); s->gprev = calloc(width, sizeof(unsigned long long));
}
static inline void incr(Sig *s, int bit, long long t, char v) {
  if (v == 'X') v = 'x';
  if (v == 'Z') v = 'z';
  int in_window = (wbeg < 0 || t >= wbeg) && (wend < 0 || t <= wend);
  unsigned long long g = G(t);
  if (s->prev_t[bit] >= 0 && in_window) {
    char p = s->prev[bit];
    long long start = s->prev_t[bit]; if (wbeg >= 0 && start < wbeg) start = wbeg;   /* clip the high interval to the window */
    if (p == '1' && t > start) { s->high[bit] += (unsigned long long)(t - start); if (g > s->gprev[bit]) s->highg[bit] += g - s->gprev[bit]; }
    if (v != p) s->tc[bit] += (v == 'x' || v == 'z' || p == 'x' || p == 'z') ? 0.5 : 1.0;
  }
  if (wend < 0 || t <= wend) { s->prev[bit] = v; s->prev_t[bit] = t; s->gprev[bit] = g; }
  if (s == gate_sig && bit == 0) {           /* the gate itself: open or close the gated interval (same instant for every other variable) */
    if (v == '1' && !gate_on) { gate_on = 1; gate_t0 = t; }
    else if (v != '1' && gate_on) { gate_cum += (t > gate_t0) ? (unsigned long long)(t - gate_t0) : 0ULL; gate_on = 0; }
  }
}
static double parse_timescale(const char *body) {   /* "1ps", "1 ns", "10ns" */
  double n = atof(body); const char *u = body; while (*u && (isdigit((unsigned char)*u) || isspace((unsigned char)*u) || *u == '.')) u++;
  double m = 1; if (!strncmp(u, "s", 1) && u[1] != 'e') m = 1; if (!strncmp(u, "ms", 2)) m = 1e-3; else if (!strncmp(u, "us", 2)) m = 1e-6; else if (!strncmp(u, "ns", 2)) m = 1e-9; else if (!strncmp(u, "ps", 2)) m = 1e-12; else if (!strncmp(u, "fs", 2)) m = 1e-15;
  return (n > 0 ? n : 1) * m;
}
int main(int argc, char **argv) {
  const char *out = NULL, *in = NULL, *outg = NULL;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "-o") && i + 1 < argc) out = argv[++i];
    else if (!strcmp(argv[i], "-g") && i + 1 < argc) outg = argv[++i];
    else if (!strcmp(argv[i], "--gate") && i + 1 < argc) gate_name = argv[++i];
    else if (!strcmp(argv[i], "--begin") && i + 1 < argc) wbeg = atoll(argv[++i]);
    else if (!strcmp(argv[i], "--end") && i + 1 < argc) wend = atoll(argv[++i]);
    else in = argv[i];
  }
  FILE *f = (!in || !strcmp(in, "-")) ? stdin : fopen(in, "r"); if (!f) { perror(in); return 1; }
  static char buf[1 << 22]; setvbuf(f, buf, _IOFBF, sizeof buf);
  char *line = NULL; size_t cap = 0; ssize_t len; int header = 1; size_t nvar = 0, nalias = 0;
  while ((len = getline(&line, &cap, f)) > 0) {
    while (len && (line[len - 1] == '\n' || line[len - 1] == '\r')) line[--len] = 0;
    if (len == 0) continue;
    if (header) {
      if (!strncmp(line, "$scope", 6)) { char typ[64], nm[256]; if (sscanf(line + 6, " %63s %255s", typ, nm) == 2) { if (depth < 63) strcpy(scope[depth], nm); depth++; } }
      else if (!strncmp(line, "$upscope", 8)) { if (depth > 0) depth--; }
      else if (!strncmp(line, "$var", 4)) {
        /* $var wire 24 , y1 [23:0] $end   |  $var wire 1 . \x[9] $end  (escaped names may contain brackets) */
        char typ[32], id[16], nm[512], rng[64] = ""; int width = 0;
        int k = sscanf(line + 4, " %31s %d %15s %511s %63s", typ, &width, id, nm, rng);
        if (k < 4 || width <= 0) continue;
        if (k == 5 && !strcmp(rng, "$end")) rng[0] = 0;
        Sig *s = find(idkey(id, strlen(id)), 1); alloc_bits(s, width);
        char path[4096]; path[0] = 0;
        for (int d = 0; d < depth && d < 63; d++) { strcat(path, scope[d]); strcat(path, "/"); }
        strcat(path, nm);
        s->alias = realloc(s->alias, (s->n_alias + 1) * sizeof(Alias)); Alias *a = &s->alias[s->n_alias++];
        a->name = strdup(path); a->width = width; a->has_range = 0; a->var_index = (int)nvar++;
        if (rng[0] == '[') { int m, l; if (sscanf(rng, "[%d:%d]", &m, &l) == 2) { a->has_range = 1; a->msb = m; a->lsb = l; } else if (sscanf(rng, "[%d]", &m) == 1) { a->has_range = 2; a->msb = a->lsb = m; } }
        if (s->n_alias > 1) nalias++;
      }
      else if (!strncmp(line, "$timescale", 10)) {
        char body[128] = ""; const char *p = line + 10; while (*p && isspace((unsigned char)*p)) p++;
        if (*p) strncpy(body, p, 127); else { if (getline(&line, &cap, f) > 0) { p = line; while (*p && isspace((unsigned char)*p)) p++; strncpy(body, p, 127); } }
        char *e = strstr(body, "$end"); if (e) *e = 0; tscale = parse_timescale(body);
      }
      else if (!strncmp(line, "$enddefinitions", 15)) { header = 0;
        if (gate_name) { for (size_t i = 0; i < nsig && !gate_sig; i++) for (int a = 0; a < sigs[i].n_alias; a++) if (!strcmp(sigs[i].alias[a].name, gate_name)) { gate_sig = &sigs[i]; break; }
          if (!gate_sig) fprintf(stderr, "vcd_toggles: WARNING gate variable %s not found, gated high times stay zero\n", gate_name);
          else if (gate_sig->width != 1) { fprintf(stderr, "vcd_toggles: gate variable %s is not 1 bit wide\n", gate_name); return 1; } } }
      continue;
    }
    char c = line[0];
    if (c == '#') { tcur = atoll(line + 1); if (tmin < 0) tmin = tcur; if (tcur > tmax) tmax = tcur; continue; }
    if (c == '0' || c == '1' || c == 'x' || c == 'z' || c == 'X' || c == 'Z') {
      Sig *s = find(idkey(line + 1, len - 1), 0); if (s) incr(s, 0, tcur, c); continue;
    }
    if (c == 'b' || c == 'B') {
      char *sp = strchr(line, ' '); if (!sp) continue; *sp = 0; const char *val = line + 1; size_t vl = strlen(val); const char *id = sp + 1;
      Sig *s = find(idkey(id, strlen(id)), 0); if (!s) continue;
      int w = s->width; char ext = (val[0] == 'x' || val[0] == 'X') ? 'x' : (val[0] == 'z' || val[0] == 'Z') ? 'z' : '0';
      for (int b = 0; b < w; b++) {            /* bit b = 0 is the most significant (first character) */
        long long pos = (long long)vl - w + b; char v = pos >= 0 ? val[pos] : ext; incr(s, b, tcur, v);
      }
      continue;
    }
    /* $dumpvars / $end / $dumpall / $comment / r-values: ignored */
  }
  if (wbeg >= 0 && (tmin < 0 || tmin < wbeg)) tmin = wbeg;          /* report the window as the duration */
  if (wend >= 0 && tmax > wend) tmax = wend;
  unsigned long long gend = G(tmax);
  FILE *o = out ? fopen(out, "w") : stdout; if (!o) { perror(out); return 1; }
  FILE *og = outg ? fopen(outg, "w") : NULL; if (outg && !og) { perror(outg); return 1; }
  fprintf(o, "#timescale_s\t%g\n#time_min\t%lld\n#time_max\t%lld\n#vars\t%zu\n#aliases\t%zu\n", tscale, tmin < 0 ? 0 : tmin, tmax, nvar, nalias);
  if (og) fprintf(og, "#timescale_s\t%g\n#time_min\t%lld\n#time_max\t%lld\n#vars\t%zu\n#aliases\t%zu\n#gate_high\t%llu\n#gate_var\t%s\n", tscale, tmin < 0 ? 0 : tmin, tmax, nvar, nalias, gend, gate_name ? gate_name : "");
  for (size_t i = 0; i < nsig; i++) {
    Sig *s = &sigs[i];
    for (int a = 0; a < s->n_alias; a++) {
      Alias *al = &s->alias[a];
      for (int b = 0; b < s->width; b++) {
        unsigned long long high = s->high[b], highg = s->highg[b];
        if (s->prev_t[b] >= 0 && s->prev[b] == '1' && tmax > s->prev_t[b]) { high += (unsigned long long)(tmax - s->prev_t[b]); if (gend > s->gprev[b]) highg += gend - s->gprev[b]; }
        if (s->width == 1 && al->has_range != 1) { fprintf(o, "%s\t%.1f\t%llu\n", al->name, s->tc[b], high); if (og) fprintf(og, "%s\t%.1f\t%llu\n", al->name, s->tc[b], highg); }
        else { int bit = al->has_range ? (al->msb >= al->lsb ? al->msb - b : al->msb + b) : (s->width - 1 - b); fprintf(o, "%s\t%.1f\t%llu\t%d\n", al->name, s->tc[b], high, bit);   /* bus bit: 4th column = bit index (the name may be an escaped identifier) */
          if (og) fprintf(og, "%s\t%.1f\t%llu\t%d\n", al->name, s->tc[b], highg, bit); }
      }
    }
  }
  if (o != stdout) fclose(o);
  if (og) fclose(og);
  if (gate_name) fprintf(stderr, "vcd_toggles: gate %s %s, gated high time %llu of %lld (%.4f)\n", gate_name, gate_sig ? "found" : "NOT FOUND", gend, tmax - (tmin < 0 ? 0 : tmin), (tmax > tmin && tmin >= 0) ? (double)gend / (double)(tmax - tmin) : 0.0);
  fprintf(stderr, "vcd_toggles: %zu ids, %zu vars (%zu aliases), time %lld..%lld x %g s\n", nsig, nvar, nalias, tmin, tmax, tscale);
  return 0;
}
