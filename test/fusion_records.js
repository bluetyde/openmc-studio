// A plow.fusion-source/0.1 record built here, shaped like the ones PLOW writes: a Miller D cut into 10 x 32 poloidal cells (rho, theta), each a ring at its centroid with a rate,
// an ion temperature and the Brysk Gaussian width. Used by test_fusion_source.js and generate_fixtures.js, so no PLOW file is needed in this repository.
function fusionRecord(o = {}) {
  const R0 = o.R0 || 2.0, a = o.a || 0.6, kappa = o.kappa || 1.7, delta = o.delta === undefined ? 0.33 : o.delta, nRho = o.nRho || 10, nTheta = o.nTheta || 32;
  const mean = o.mean || 14.071, s = Math.asin(delta), cells = [];
  let sum = 0;
  for (let i = 0; i < nRho; i++) {
    for (let j = 0; j < nTheta; j++) {
      const rho = (i + 0.5) / nRho, th = 2 * Math.PI * (j + 0.5) / nTheta;
      const r = R0 + a * rho * Math.cos(th + s * Math.sin(th)), z = kappa * a * rho * Math.sin(th);
      const ti = 1 + 15 * Math.pow(1 - rho * rho, 1.5), rate = Math.pow(1 - rho * rho, 2) * rho * r * (o.shape || 1);
      cells.push({rho: [i / nRho, (i + 1) / nRho], theta: [2 * Math.PI * j / nTheta, 2 * Math.PI * (j + 1) / nTheta], r_m: r, z_m: z, ti_kev: ti, rate_n_s: rate, energy_std_mev: 0.177 * Math.sqrt(ti) / 2.355});
      sum += rate;
    }
  }
  const total = o.total || 4.0e19;
  cells.forEach(c => { c.rate_n_s *= total / sum; });
  return {schema: 'plow.fusion-source/0.1', name: 'synthetic D', reaction: 'D-T',
          neutron: {energy_mean_mev: mean, spread: 'gaussian', direction: 'isotropic'},
          total_rate_n_per_s: total, power_neutron_mw: total * mean * 1.602176634e-13 * 1e-6, grid: {n_rho: nRho, n_theta: nTheta}, cells};
}
module.exports = {fusionRecord};
