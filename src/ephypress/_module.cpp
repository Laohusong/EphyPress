// SPDX-License-Identifier: MIT
#include <Python.h>
static PyModuleDef module = {PyModuleDef_HEAD_INIT, "_codec", "EphyPress delta/rANS codec.", -1, nullptr};
PyMODINIT_FUNC PyInit__codec(void) { return PyModule_Create(&module); }
