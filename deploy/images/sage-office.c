#include <LibreOfficeKit/LibreOfficeKitInit.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void report_error(LibreOfficeKit *office, const char *operation)
{
    char *detail = office->pClass->getError(office);
    fprintf(stderr, "%s: %s\n", operation, detail ? detail : "unknown error");
    free(detail);
}

int main(int argc, char **argv)
{
    if (argc != 4 || strncmp(argv[1], "file:///", 8) != 0 || argv[2][0] != '/' || argv[3][0] != '/') {
        fprintf(stderr, "Usage: sage-office file:///profile /absolute/input /absolute/output.pdf|xlsx\n");
        return EXIT_FAILURE;
    }
    const char *extension = strrchr(argv[3], '.');
    if (!extension || (strcmp(extension, ".pdf") != 0 && strcmp(extension, ".xlsx") != 0)) {
        fprintf(stderr, "Output format must be PDF or XLSX\n");
        return EXIT_FAILURE;
    }
    LibreOfficeKit *office = lok_init_2("/usr/lib/libreoffice/program", argv[1]);
    if (!office) {
        fprintf(stderr, "Could not initialize LibreOfficeKit\n");
        return EXIT_FAILURE;
    }
    LibreOfficeKitDocument *document = office->pClass->documentLoad(office, argv[2]);
    if (!document) {
        report_error(office, "Could not read Office document");
        office->pClass->destroy(office);
        return EXIT_FAILURE;
    }
    int saved = document->pClass->saveAs(document, argv[3], extension + 1, NULL);
    if (!saved) {
        report_error(office, "Could not convert Office document");
    }
    document->pClass->destroy(document);
    office->pClass->destroy(office);
    return saved ? EXIT_SUCCESS : EXIT_FAILURE;
}
