import {evaluate} from './gate.mjs';
export default {
  id:'olive-invest-closure',
  name:'Olive investing execution closure',
  register(api) {
    api.registerTrustedToolPolicy({
      id:'investment-phase-budget',
      description:'Stop new research only for host-recorded simulated investment runs; retain existing authorization.',
      evaluate
    });
  }
};
