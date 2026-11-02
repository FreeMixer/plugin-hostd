/* Instantiate one LV2 plugin by its binary and descriptor index and print FPCR before and after:
 *   fpcr-init <plugin.so> <uri> <bundle path/>          aarch64 only */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <lv2/core/lv2.h>
#include <lv2/urid/urid.h>

static char *uris[4096];
static unsigned n_uris;
static LV2_URID map(LV2_URID_Map_Handle h, const char *uri)
{
    (void)h;
    for (unsigned i = 0; i < n_uris; i++)
        if (!strcmp(uris[i], uri))
            return i + 1;
    uris[n_uris] = strdup(uri);
    return ++n_uris;
}
static const char *unmap(LV2_URID_Unmap_Handle h, LV2_URID u) { (void)h; return u && u <= n_uris ? uris[u - 1] : NULL; }

static uint64_t fpcr(void) { uint64_t v; __asm__ volatile("mrs %0, fpcr" : "=r"(v)); return v; }

int main(int argc, char **argv)
{
    if (argc != 4)
        return 2;
    uint64_t pre = fpcr();
    void *so = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    printf("dlopen %s: fpcr before 0x%08llx after 0x%08llx\n", argv[1], (unsigned long long)pre, (unsigned long long)fpcr());
    if (!so) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    LV2_Descriptor_Function f = (LV2_Descriptor_Function)dlsym(so, "lv2_descriptor");
    const LV2_Descriptor *d = NULL;
    for (uint32_t i = 0; f && (d = f(i)); i++)
        if (!strcmp(d->URI, argv[2]))
            break;
    if (!d) { fprintf(stderr, "no descriptor %s\n", argv[2]); return 1; }
    LV2_URID_Map m = { NULL, map };
    LV2_URID_Unmap um = { NULL, unmap };
    LV2_Feature fm = { LV2_URID__map, &m }, fu = { LV2_URID__unmap, &um };
    const LV2_Feature *feats[] = { &fm, &fu, NULL };
    if (getenv("FPCR_ZERO")) __asm__ volatile("msr fpcr, %0" :: "r"((uint64_t)0));
    uint64_t before = fpcr();
    LV2_Handle h = d->instantiate(d, 48000.0, argv[3], feats);
    uint64_t after = fpcr();
    printf("%s: fpcr before 0x%08llx after 0x%08llx changed 0x%08llx (FZ bit24 %s, AH bit1 %s, FIZ bit0 %s, DN bit25 %s)\n",
           argv[2], (unsigned long long)before, (unsigned long long)after, (unsigned long long)(before ^ after),
           ((before ^ after) >> 24) & 1 ? "changed" : "same", ((before ^ after) >> 1) & 1 ? "changed" : "same",
           (before ^ after) & 1 ? "changed" : "same", ((before ^ after) >> 25) & 1 ? "changed" : "same");
    if (h && d->cleanup)
        d->cleanup(h);
    return 0;
}
