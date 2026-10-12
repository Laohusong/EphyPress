#include <Python.h>
#include "fse.h"

static PyModuleDef module = {PyModuleDef_HEAD_INIT, "_codec", "Bundled EphyPress native codec.", -1, nullptr};

PyMODINIT_FUNC PyInit__codec(void) {
    PyObject *result = PyModule_Create(&module);
    if (!result) return nullptr;
#ifdef _OPENMP
    const int openmp = 1;
#else
    const int openmp = 0;
#endif
    if (PyModule_AddIntConstant(result, "openmp_enabled", openmp) < 0 ||
        PyModule_AddIntConstant(result, "fse_version_number", FSE_versionNumber()) < 0) {
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}
