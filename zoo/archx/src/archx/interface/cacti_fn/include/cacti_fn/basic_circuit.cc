/*------------------------------------------------------------
 *                              CACTI 6.5
 *         Copyright 2008 Hewlett-Packard Development Corporation
 *                         All Rights Reserved
 *
 * Permission to use, copy, and modify this software and its documentation is
 * hereby granted only under the following terms and conditions.  Both the
 * above copyright notice and this permission notice must appear in all copies
 * of the software, derivative works or modified versions, and any portions
 * thereof, and both notices must appear in supporting documentation.
 *
 * Users of this software agree to the terms and conditions set forth herein, and
 * hereby grant back to Hewlett-Packard Company and its affiliated companies ("HP")
 * a non-exclusive, unrestricted, royalty-free right and license under any changes, 
 * enhancements or extensions  made to the core functions of the software, including 
 * but not limited to those affording compatibility with other hardware or software
 * environments, but excluding applications which incorporate this software.
 * Users further agree to use their best efforts to return to HP any such changes,
 * enhancements or extensions that they make and inform HP of noteworthy uses of
 * this software.  Correspondence should be provided to HP at:
 *
 *                       Director of Intellectual Property Licensing
 *                       Office of Strategy and Technology
 *                       Hewlett-Packard Company
 *                       1501 Page Mill Road
 *                       Palo Alto, California  94304
 *
 * This software may be distributed (but not offered for sale or transferred
 * for compensation) to third parties, provided such third parties agree to
 * abide by the terms and conditions of this notice.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND HP DISCLAIMS ALL
 * WARRANTIES WITH REGARD TO THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES
 * OF MERCHANTABILITY AND FITNESS.   IN NO EVENT SHALL HP 
 * CORPORATION BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL
 * DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR
 * PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
 * ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS
 * SOFTWARE.
 *------------------------------------------------------------*/


#include "basic_circuit.h"
#include "parameter.h"
#include <iostream>
#include <assert.h>

uint32_t _log2(uint64_t num)
{
  uint32_t log2 = 0;

  if (num == 0)
  {
    std::cerr << "log0?" << std::endl;
    exit(1);
  }

  while (num > 1)
  {
    num = (num >> 1);
    log2++;
  }

  return log2;
}


bool is_pow2(int64_t val)
{
  if (val <= 0)
  {
    return false;
  }
  else if (val == 1)
  {
    return true;
  }
  else
  {
    return (_log2(val) != _log2(val-1));
  }
}


int powers (int base, int n)
{
  int i, p;

  p = 1;
  for (i = 1; i <= n; ++i)
    p *= base;
  return p;
}

int factorial(int n, int m)
{
	int fa = m, i;
	for (i=m+1; i<=n; i++)
		fa *=i;
	return fa;
}

int combination(int n, int m)
{
  int ret;
  ret = factorial(n, m+1) / factorial(n - m);
  return ret;
}

/*----------------------------------------------------------------------*/

double logtwo (double x)
{
  assert(x > 0);
  return ((double) (log (x) / log (2.0)));
}

/*----------------------------------------------------------------------*/


double gate_C(
    double width,
    double wirelength,
    bool   _is_dram,
    bool   _is_cell,
    bool   _is_wl_tr)
{
  const TechnologyParameter::DeviceType * dt;

  if (_is_dram && _is_cell)
  { 
    dt = &g_tp.dram_acc;   //DRAM cell access transistor
  }
  else if (_is_dram && _is_wl_tr)
  {
    dt = &g_tp.dram_wl;    //DRAM wordline transistor
  }
  else if (!_is_dram && _is_cell)
  {
    dt = &g_tp.sram_cell;  // SRAM cell access transistor
  }
  else
  {
    dt = &g_tp.peri_global;
  }

  /***** Alireza - BEGIN *****/
  double Cg;
//  cout << "Cpolywire : " <<Cpolywire << endl; //Cpolywire = 0 always
// Divya Changing begin
    if ( g_ip->is_finfet) {
    double W_min = 2 * dt->H_fin + dt->W_fin; //2 * dt->H_fin;(original) //Divya changed
    int N_fin = (int) (ceil(width / W_min));
//    Cg = (dt->C_g_ideal + dt->C_overlap + 3*dt->C_fringe)*W_min*N_fin + dt->l_phy*Cpolywire;
    Cg = (dt->C_g_ideal)*W_min*N_fin; //Divya changed
  } else {
  Cg = (dt->C_g_ideal + dt->C_overlap + 3*dt->C_fringe)*width + dt->l_phy*Cpolywire;
  }
  return Cg;
  /****** Alireza - END ******/
}


// returns gate capacitance in Farads
// actually this function is the same as gate_C() now
double gate_C_pass(
    double width,       // gate width in um (length is Lphy_periph_global)
    double wirelength,  // poly wire length going to gate in lambda
    bool   _is_dram,
    bool   _is_cell,
    bool   _is_wl_tr)
{
  // v5.0
  const TechnologyParameter::DeviceType * dt;

  if ((_is_dram) && (_is_cell))
  { 
    dt = &g_tp.dram_acc;   //DRAM cell access transistor
  }
  else if ((_is_dram) && (_is_wl_tr))
  {
    dt = &g_tp.dram_wl;    //DRAM wordline transistor
  }
  else if ((!_is_dram) && _is_cell)
  {
    dt = &g_tp.sram_cell;  // SRAM cell access transistor
  }
  else
  {
    dt = &g_tp.peri_global;
  }

  /***** Alireza - BEGIN *****/
  double Cg;
  // Divya Changing begin
  //  As W_fin != 2*H_fin.  We have width given, no need to derive from H_fin.
  if ( g_ip->is_finfet ) {
    double W_min = 2 * dt->H_fin + dt->W_fin; //dt->W_fin; //2 * dt->H_fin;(original) //Divya changed
    int N_fin = (int) (ceil(width / W_min));
 //   	cout << "gate_C_pass :: width " << width << ", W_min : " << W_min << ", N_fin : " << N_fin << endl;
//   	Cg = (dt->C_g_ideal + dt->C_overlap + 3*dt->C_fringe)*W_min*N_fin + dt->l_phy*Cpolywire;
    Cg = (dt->C_g_ideal)*W_min*N_fin; //Divya changed
  } else {
  Cg = (dt->C_g_ideal + dt->C_overlap + 3*dt->C_fringe)*width + dt->l_phy*Cpolywire;
  }
  return Cg;
  /****** Alireza - END ******/
}


double drain_C_(
    double width,
    int nchannel,
    int stack,
    int next_arg_thresh_folding_width_or_height_cell,
    double fold_dimension,
    bool _is_dram,
    bool _is_cell,
    bool _is_wl_tr)
{
  double w_folded_tr;
  const  TechnologyParameter::DeviceType * dt;

  if ((_is_dram) && (_is_cell))
  { 
    dt = &g_tp.dram_acc;   // DRAM cell access transistor
  }
  else if ((_is_dram) && (_is_wl_tr))
  {
    dt = &g_tp.dram_wl;    // DRAM wordline transistor
  }
  else if ((!_is_dram) && _is_cell)
  {
    dt = &g_tp.sram_cell;  // SRAM cell access transistor
  }
  else
  {
    dt = &g_tp.peri_global;
  }

  double c_junc_area = dt->C_junc;
  double c_junc_sidewall = dt->C_junc_sidewall;
  double c_fringe    = 2*dt->C_fringe;
  double c_overlap   = 2*dt->C_overlap;
  double drain_C_metal_connecting_folded_tr = 0;

  // determine the width of the transistor after folding (if it is getting folded)
  if (next_arg_thresh_folding_width_or_height_cell == 0)
  { // interpret fold_dimension as the the folding width threshold 
    // i.e. the value of transistor width above which the transistor gets folded
    w_folded_tr = fold_dimension;
  } 
  else
  { // interpret fold_dimension as the height of the cell that this transistor is part of. 
    double h_tr_region  = fold_dimension - 2 * g_tp.HPOWERRAIL;
    // TODO : w_folded_tr must come from Component::compute_gate_area()
    double ratio_p_to_n = 2.0 / (2.0 + 1.0);
    if (nchannel)
    {
      w_folded_tr = (1 - ratio_p_to_n) * (h_tr_region - g_tp.MIN_GAP_BET_P_AND_N_DIFFS);
    }
    else
    {
      w_folded_tr = ratio_p_to_n * (h_tr_region - g_tp.MIN_GAP_BET_P_AND_N_DIFFS);
    }
  }

  /***** Alireza - BEGIN *****/
  int N_fin = 1;
  int N_fin_in_each_fold = 1;
  int num_folded_tr;
  // Divya Changing begin
   // As W_fin != 2*H_fin.  We have width given, no need to derive from H_fin.
   if ( g_ip->is_finfet ) {
    double W_min = 2 * dt->H_fin + dt->W_fin; //dt->W_fin;	//2 * dt->H_fin;(original) //Divya changed
    N_fin = (int) (ceil(width / W_min));

    int N_fin_max = (int) (floor(w_folded_tr / dt->P_fin)); // + 1;
	 if ( N_fin_max == 0 ) {
//		 cout << "next_arg_thresh_folding_width_or_height_cell: " << next_arg_thresh_folding_width_or_height_cell << endl;
//		 cout << "ERROR: divide by zero in drain_C_ function!\n";
//		 cout << "width: " << width << ", W_min: " << W_min << ", N_fin: " << N_fin
//				 << ", w_folded_tr: " << w_folded_tr << ", P_fin: " << dt->P_fin << ", folddimension: " << fold_dimension << endl;
		 N_fin_max = 1;	//divya adding 22-11-2021
//		 exit(0); //divya removing 22-11-2021
	 }
	 num_folded_tr = (int) (ceil((double)N_fin / N_fin_max));
	 N_fin_in_each_fold = (int) (ceil((double)N_fin / num_folded_tr));
//	 cout << "width : " << width << ", W_min : " << W_min << ", N_fin : " << N_fin << ", N_fin_max : " << N_fin_max << endl;
  } else {
  num_folded_tr = (int) (ceil(width / w_folded_tr));
    if (num_folded_tr < 2) { w_folded_tr = width; } // originally in cacti
    w_folded_tr = width / (double)num_folded_tr;	// not there in original cacti
  }
  /****** Alireza - END ******/
 
  double spacing_poly_contact_poly = g_tp.w_poly_contact + 2 * g_tp.spacing_poly_to_contact;
  double total_drain_w = spacing_poly_contact_poly +  // only for drain
                         (stack - 1) * g_tp.spacing_poly_to_poly;

  /***** Alireza - BEGIN *****/
  double drain_h_for_sidewall;
   if ( g_ip->is_finfet ) {
    drain_h_for_sidewall = dt->T_si;
  } else {
  drain_h_for_sidewall = w_folded_tr;
  }
  /****** Alireza - END ******/
  
  double total_drain_height_for_cap_wrt_gate = w_folded_tr + 2 * w_folded_tr * (stack - 1); ///
  
  if (num_folded_tr > 1)
  {
    total_drain_w += (num_folded_tr - 2) * (spacing_poly_contact_poly) +
                     (num_folded_tr - 1) * ((stack - 1) * g_tp.spacing_poly_to_poly);

    if (num_folded_tr%2 == 0)
    {
      drain_h_for_sidewall = 0;
    }
    total_drain_height_for_cap_wrt_gate *= num_folded_tr;
    drain_C_metal_connecting_folded_tr   = g_tp.wire_local.C_per_um * total_drain_w;
  }

  /***** Alireza - BEGIN *****/
  double drain_C_area;
  double drain_C_sidewall;
  double drain_C_wrt_gate;
  // Divya Changing begin
   if ( g_ip->is_finfet ) {
    drain_C_area     = c_junc_area * total_drain_w * dt->T_si * N_fin_in_each_fold;
    drain_C_sidewall = c_junc_sidewall * (drain_h_for_sidewall + 2 * total_drain_w) * N_fin_in_each_fold;
    drain_C_wrt_gate = 0;//(c_fringe + c_overlap) * N_fin * 2 * dt->H_fin; // According to BSIM-CMG, this capacitance is zero for FinFETs.
  } else {
 //Divya end
    drain_C_area     = c_junc_area * total_drain_w * w_folded_tr;
    drain_C_sidewall = c_junc_sidewall * (drain_h_for_sidewall + 2 * total_drain_w);
    drain_C_wrt_gate = (c_fringe + c_overlap) * total_drain_height_for_cap_wrt_gate;
  }
  /****** Alireza - END ******/
  
  return (drain_C_area + drain_C_sidewall + drain_C_wrt_gate + drain_C_metal_connecting_folded_tr);
}


double tr_R_on(
    double width,
    int nchannel,
    int stack,
    bool _is_dram,
    bool _is_cell,
    bool _is_wl_tr)
{
  const TechnologyParameter::DeviceType * dt;

  if ((_is_dram) && (_is_cell))
  {
    dt = &g_tp.dram_acc;   //DRAM cell access transistor
  }
  else if ((_is_dram) && (_is_wl_tr))
  {
    dt = &g_tp.dram_wl;    //DRAM wordline transistor
  }
  else if ((!_is_dram) && _is_cell)
  {
    dt = &g_tp.sram_cell;  // SRAM cell access transistor
  }
  else
  {
    dt = &g_tp.peri_global;
  }

  double restrans = (nchannel) ? dt->R_nch_on : dt->R_pch_on;
  
  /***** Alireza - BEGIN *****/
    if ( g_ip->is_finfet ) {
    double W_min = 2 * dt->H_fin + dt->W_fin; //dt->W_fin; //2 * dt->H_fin;(original) //Divya changed
    double width_eff = ceil(width / W_min) * W_min; // effective width = Nfin * Wmin
    return (stack * restrans / width_eff);
  } else {
  return (stack * restrans / width);
  }
  /****** Alireza - END ******/
}


/* This routine operates in reverse: given a resistance, it finds
 * the transistor width that would have this R.  It is used in the
 * data wordline to estimate the wordline driver size. */

// returns width in um
double R_to_w(
    double res,
    int   nchannel,
    bool _is_dram,
    bool _is_cell,
    bool _is_wl_tr)
{
  const TechnologyParameter::DeviceType * dt;

  if ((_is_dram) && (_is_cell))
  { 
    dt = &g_tp.dram_acc;   //DRAM cell access transistor
  }
  else if ((_is_dram) && (_is_wl_tr))
  {
    dt = &g_tp.dram_wl;    //DRAM wordline transistor
  }
  else if ((!_is_dram) && (_is_cell))
  {
    dt = &g_tp.sram_cell;  // SRAM cell access transistor
  }
  else
  {
    dt = &g_tp.peri_global;
  }

  double restrans = (nchannel) ? dt->R_nch_on : dt->R_pch_on;
  return (restrans / res);
}


double pmos_to_nmos_sz_ratio(
    bool _is_dram,
    bool _is_wl_tr)
{
  double p_to_n_sizing_ratio;
  if ((_is_dram) && (_is_wl_tr))
  { //DRAM wordline transistor
    p_to_n_sizing_ratio = g_tp.dram_wl.n_to_p_eff_curr_drv_ratio;
  }
  else
  { //DRAM or SRAM all other transistors
    p_to_n_sizing_ratio = g_tp.peri_global.n_to_p_eff_curr_drv_ratio;
  }
  return p_to_n_sizing_ratio;
}


// "Timing Models for MOS Circuits" by Mark Horowitz, 1984
double horowitz(
    double inputramptime, // input rise time
    double tf,            // time constant of gate
    double vs1,           // threshold voltage
    double vs2,           // threshold voltage
    int    rise)          // whether input rises or fall
{
  if (inputramptime == 0 && vs1 == vs2)
  {
    return tf * (vs1 < 1 ? -log(vs1) : log(vs1));
  }
  double a, b, td;

  a = inputramptime / tf;
  if (rise == RISE)
  {
    b = 0.5;
    td = tf * sqrt(log(vs1)*log(vs1) + 2*a*b*(1.0 - vs1)) + tf*(log(vs1) - log(vs2));
  }
  else
  {
    b = 0.4;
    td = tf * sqrt(log(1.0 - vs1)*log(1.0 - vs1) + 2*a*b*(vs1)) + tf*(log(1.0 - vs1) - log(1.0 - vs2));
  }
  return (td);
}


double cmos_Ileak(
    double nWidth,
    double pWidth,
    bool _is_dram,
    bool _is_cell,
    bool _is_wl_tr)
{
  TechnologyParameter::DeviceType * dt;

  if ((!_is_dram)&&(_is_cell))
  { //SRAM cell access transistor
    dt = &(g_tp.sram_cell);
  }
  else if ((_is_dram)&&(_is_wl_tr))
  { //DRAM wordline transistor
    dt = &(g_tp.dram_wl);
  }
  else
  { //DRAM or SRAM all other transistors
    dt = &(g_tp.peri_global);
  }
  
  /***** Alireza - BEGIN *****/
//  Divya changing begin
  if ( g_ip->is_finfet ) {
    double W_min = 2 * dt->H_fin + dt->W_fin; //dt->W_fin; //2 * dt->H_fin;(original) //Divya changed
    double nWidth_eff = ceil(nWidth / W_min) * W_min; // effective nwidth = Nfin * Wmin
    double pWidth_eff = ceil(pWidth / W_min) * W_min; // effective pwidth = Nfin * Wmin
    return nWidth_eff*dt->I_off_n + pWidth_eff*dt->I_off_p;
  } else {
   return nWidth*dt->I_off_n + pWidth*dt->I_off_p;
  }
  /****** Alireza - END ******/
}


double simplified_nmos_leakage(
    double nwidth,
    bool _is_dram,
    bool _is_cell,
    bool _is_wl_tr)
{
  TechnologyParameter::DeviceType * dt;

  if ((!_is_dram)&&(_is_cell))
  { //SRAM cell access transistor
    dt = &(g_tp.sram_cell);
  }
  else if ((_is_dram)&&(_is_wl_tr))
  { //DRAM wordline transistor
    dt = &(g_tp.dram_wl);
  }
  else
  { //DRAM or SRAM all other transistors
    dt = &(g_tp.peri_global);
  }
  
  /***** Alireza - BEGIN *****/
  if ( g_ip->is_finfet ) {
    double W_min = 2 * dt->H_fin + dt->W_fin; //dt->W_fin; //2 * dt->H_fin;(original) //Divya chnaged
    double nwidth_eff = ceil(nwidth/W_min) * W_min; // effective nwidth = Nfin * Wmin
    return nwidth_eff * dt->I_off_n;
  } else {
  return nwidth * dt->I_off_n;
  }
  /****** Alireza - END ******/
}


double simplified_pmos_leakage(
    double pwidth,
    bool _is_dram,
    bool _is_cell,
    bool _is_wl_tr)
{
  TechnologyParameter::DeviceType * dt;

  if ((!_is_dram)&&(_is_cell))
  { //SRAM cell access transistor
    dt = &(g_tp.sram_cell);
  }
  else if ((_is_dram)&&(_is_wl_tr))
  { //DRAM wordline transistor
    dt = &(g_tp.dram_wl);
  }
  else
  { //DRAM or SRAM all other transistors
    dt = &(g_tp.peri_global);
  }

  /***** Alireza - BEGIN *****/
  if ( g_ip->is_finfet ) {
    double W_min = 2 * dt->H_fin + dt->W_fin; //dt->W_fin; //2 * dt->H_fin;(original) //Divya changed
    double pwidth_eff = ceil(pwidth / W_min) * W_min; // effective pwidth = Nfin * Wmin
    return pwidth_eff * dt->I_off_p;
  } else {
  return pwidth * dt->I_off_p;
  }
  /****** Alireza - END ******/
}

//divya 19-11-2021 for mcpat
double cmos_Isub_leakage(
    double nWidth,
    double pWidth,
    int    fanin,
    enum Gate_type g_type,
    bool _is_dram,
    bool _is_cell,
    bool _is_wl_tr,
    bool _is_sleep_tx,
    enum Half_net_topology topo)
{
	assert (fanin>=1);
	double nmos_leak = simplified_nmos_leakage(nWidth, _is_dram, _is_cell, _is_wl_tr);	//, _is_sleep_tx);
	double pmos_leak = simplified_pmos_leakage(pWidth, _is_dram, _is_cell, _is_wl_tr);	//, _is_sleep_tx);
    double Isub=0;
    int    num_states;
    int    num_off_tx;

    num_states = int(pow(2.0, fanin));

    switch (g_type)
    {
    case nmos:
    	if (fanin==1)
    	{
    		Isub = nmos_leak/num_states;
    	}
    	else
    	{
    		if (topo==parallel)
    		{
    			Isub=nmos_leak*fanin/num_states; //only when all tx are off, leakage power is non-zero. The possibility of this state is 1/num_states
    		}
    		else
    		{
    			for (num_off_tx=1; num_off_tx<=fanin; num_off_tx++) //when num_off_tx ==0 there is no leakage power
    			{
    				//Isub += nmos_leak*pow(UNI_LEAK_STACK_FACTOR,(num_off_tx-1))*(factorial(fanin)/(factorial(fanin, num_off_tx)*factorial(num_off_tx)));
    				Isub += nmos_leak*pow(UNI_LEAK_STACK_FACTOR,(num_off_tx-1))*combination(fanin, num_off_tx);
    			}
    			Isub /=num_states;
    		}

    	}
    	break;
    case pmos:
    	if (fanin==1)
    	{
    		Isub = pmos_leak/num_states;
    	}
    	else
    	{
    		if (topo==parallel)
    		{
    			Isub=pmos_leak*fanin/num_states; //only when all tx are off, leakage power is non-zero. The possibility of this state is 1/num_states
    		}
    		else
    		{
    			for (num_off_tx=1; num_off_tx<=fanin; num_off_tx++) //when num_off_tx ==0 there is no leakage power
    			{
    				//Isub += pmos_leak*pow(UNI_LEAK_STACK_FACTOR,(num_off_tx-1))*(factorial(fanin)/(factorial(fanin, num_off_tx)*factorial(num_off_tx)));
    				Isub += pmos_leak*pow(UNI_LEAK_STACK_FACTOR,(num_off_tx-1))*combination(fanin, num_off_tx);
    			}
    			Isub /=num_states;
    		}

    	}
    	break;
    case inv:
    	Isub = (nmos_leak + pmos_leak)/2;
    	break;
    case nand:
    	Isub += fanin*pmos_leak;//the pullup network
    	for (num_off_tx=1; num_off_tx<=fanin; num_off_tx++) // the pulldown network
    	{
    		//Isub += nmos_leak*pow(UNI_LEAK_STACK_FACTOR,(num_off_tx-1))*(factorial(fanin)/(factorial(fanin, num_off_tx)*factorial(num_off_tx)));
            Isub += nmos_leak*pow(UNI_LEAK_STACK_FACTOR,(num_off_tx-1))*combination(fanin, num_off_tx);
    	}
    	Isub /=num_states;
    	break;
    case nor:
    	for (num_off_tx=1; num_off_tx<=fanin; num_off_tx++) // the pullup network
    	{
    		//Isub += pmos_leak*pow(UNI_LEAK_STACK_FACTOR,(num_off_tx-1))*(factorial(fanin)/(factorial(fanin, num_off_tx)*factorial(num_off_tx)));
    		Isub += pmos_leak*pow(UNI_LEAK_STACK_FACTOR,(num_off_tx-1))*combination(fanin, num_off_tx);
    	}
    	Isub += fanin*nmos_leak;//the pulldown network
    	Isub /=num_states;
    	break;
    case tri:
    	Isub += (nmos_leak + pmos_leak)/2;//enabled
    	Isub += nmos_leak*UNI_LEAK_STACK_FACTOR; //disabled upper bound of leakage power
    	Isub /=2;
    	break;
    case tg:
    	Isub = (nmos_leak + pmos_leak)/2;
    	break;
    default:
    	assert(0);
    	break;
	  }

    return Isub;
}

//divya 19-11-2021
double cmos_Ig_leakage(
    double nWidth,
    double pWidth,
    int    fanin,
    enum Gate_type g_type,
    bool _is_dram,
    bool _is_cell,
    bool _is_wl_tr,
    bool _is_sleep_tx,
    enum Half_net_topology topo)
{
	return 0;
}

