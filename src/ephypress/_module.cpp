#include <Python.h>
#include "fse.h"
#include "_prediction.h"

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
        PyModule_AddIntConstant(result, "fse_version_number", FSE_versionNumber()) < 0 ||
        PyModule_AddIntConstant(result, "temporal_numerator", ephypress::kTemporalNumerator) < 0 ||
        PyModule_AddIntConstant(result, "temporal_denominator", ephypress::kTemporalDenominator) < 0 ||
        PyModule_AddIntConstant(result, "spatial_denominator", ephypress::kSpatialDenominator) < 0) {
        Py_DECREF(result);
        return nullptr;
    }
    PyObject *weights = Py_BuildValue("(iiii)", ephypress::kSpatialWeights[0], ephypress::kSpatialWeights[1],
                                     ephypress::kSpatialWeights[2], ephypress::kSpatialWeights[3]);
    if (!weights || PyModule_AddObject(result, "spatial_weights", weights) < 0) {
        Py_XDECREF(weights);
        Py_DECREF(result);
        return nullptr;
    }
    return result;
}
