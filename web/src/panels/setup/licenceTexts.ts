import agpl3 from "./licences/AGPL-3.0.txt?raw";
import apache2 from "./licences/Apache-2.0.txt?raw";
import bsd3 from "./licences/BSD-3-Clause.txt?raw";
import gpl2 from "./licences/GPL-2.0.txt?raw";
import gpl3 from "./licences/GPL-3.0.txt?raw";
import lgpl21 from "./licences/LGPL-2.1.txt?raw";
import mit from "./licences/MIT.txt?raw";
import psf from "./licences/PSF-2.0.txt?raw";
import type { LicenceTextKey } from "../../state/setup";

export const LICENCE_TEXTS: Record<LicenceTextKey, string> = {
  "GPL-2.0": gpl2,
  "GPL-3.0": gpl3,
  "AGPL-3.0": agpl3,
  "LGPL-2.1": lgpl21,
  MIT: mit,
  "Apache-2.0": apache2,
  "BSD-3-Clause": bsd3,
  "PSF-2.0": psf,
};
