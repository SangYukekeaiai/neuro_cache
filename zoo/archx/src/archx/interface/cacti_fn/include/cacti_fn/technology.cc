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

#include <iostream> // Alireza
#include "basic_circuit.h"
#include "parameter.h"
#include "xmlParser.h"	// Majid
using namespace std; // Alireza


double wire_resistance(double resistivity, double wire_width, double wire_thickness,
    double barrier_thickness, double dishing_thickness, double alpha_scatter)
{
  double resistance;
  resistance = alpha_scatter * resistivity /((wire_thickness - barrier_thickness - dishing_thickness)*(wire_width - 2 * barrier_thickness));
  return(resistance);
}


double wire_capacitance(double wire_width, double wire_thickness, double wire_spacing, 
    double ild_thickness, double miller_value, double horiz_dielectric_constant,
    double vert_dielectric_constant, double fringe_cap)
{
  double vertical_cap, sidewall_cap, total_cap;
  vertical_cap = 2 * PERMITTIVITY_FREE_SPACE * vert_dielectric_constant * wire_width / ild_thickness;
  sidewall_cap = 2 * PERMITTIVITY_FREE_SPACE * miller_value * horiz_dielectric_constant * wire_thickness / wire_spacing;
  total_cap = vertical_cap + sidewall_cap + fringe_cap;
  return(total_cap);
}


void init_tech_params(double technology, double wire_technology, bool is_tag) //Divya added wire_technology
{
	int    iter, tech, tech_lo, tech_hi;
	double curr_alpha, curr_vpp;
/*	double aspect_ratio, wire_width, wire_thickness, wire_spacing, barrier_thickness, dishing_thickness,
			 alpha_scatter, ild_thickness, miller_value = 1.5, horiz_dielectric_constant, vert_dielectric_constant,
			 fringe_cap, pmos_to_nmos_sizing_r;
*/
	  double wire_width, wire_thickness, wire_spacing,
	         fringe_cap, pmos_to_nmos_sizing_r;
	  double barrier_thickness, dishing_thickness, alpha_scatter;

	double curr_vdd_dram_cell, curr_v_th_dram_access_transistor, curr_I_on_dram_cell, curr_c_dram_cell;

	// TO DO: remove 'ram_cell_tech_type'.
	uint32_t ram_cell_tech_type    = (is_tag) ? g_ip->tag_arr_ram_cell_tech_type : g_ip->data_arr_ram_cell_tech_type;
	//uint32_t peri_global_tech_type = (is_tag) ? g_ip->tag_arr_peri_global_tech_type : g_ip->data_arr_peri_global_tech_type;

	technology  = technology * 1000.0;  // in the unit of nm
	wire_technology = wire_technology * 1000.0;	//in the unit of nm //Divya added

	// initialize parameters
	g_tp.reset();
	double gmp_to_gmn_multiplier_periph_global = 0; 

	double curr_Wmemcella_dram, curr_Wmemcellpmos_dram, curr_Wmemcellnmos_dram,
			 curr_area_cell_dram, curr_asp_ratio_cell_dram, curr_Wmemcella_sram,
			 curr_Wmemcellpmos_sram, curr_Wmemcellnmos_sram, curr_Wmemcellrda_sram = 0,
			 curr_Wmemcellrdiso_sram = 0, curr_area_cell_sram, curr_asp_ratio_cell_sram,
			 curr_I_off_dram_cell_worst_case_length_temp;
   double curr_Wmemcella_cam, curr_Wmemcellpmos_cam, curr_Wmemcellnmos_cam, curr_area_cell_cam,//Sheng: CAM data
	         curr_asp_ratio_cell_cam;
	double SENSE_AMP_D, SENSE_AMP_P; // s, J
	double area_cell_dram = 0;
	double asp_ratio_cell_dram = 0;
	double area_cell_sram = 0;
	double asp_ratio_cell_sram = 0;
	  double area_cell_cam = 0;
	  double asp_ratio_cell_cam = 0;
	double mobility_eff_periph_global = 0;
	double Vdsat_periph_global = 0;
	double width_dram_access_transistor;

	/***** Alireza2 - BEGIN *****/
	// Alireza: 5, 7, 14, 16, and 22 are added
//	cout << "tech: " << technology << endl;
	if ( technology == 90 ) {        // 90nm CMOS
		tech_lo = 90; tech_hi = 90;
	} else if ( technology == 65 ) { // 65nm CMOS
		tech_lo = 65; tech_hi = 65;
	} else if ( technology == 45 ) { // 45nm CMOS
		tech_lo = 45; tech_hi = 45;
	} else if ( technology == 32 ) { // 32nm CMOS
		tech_lo = 32; tech_hi = 32;
	} else if ( technology == 22 ) { // 22nm CMOS
		tech_lo = 22; tech_hi = 22;
	} else if ( technology == 16 ) { // 16nm CMOS
		tech_lo = 16; tech_hi = 16;
	} else if ( technology == 14 ) { // 14nm CMOS
		tech_lo = 14; tech_hi = 14;
	} else if ( technology == 7 ) {  // 7nm FinFET
		tech_lo = 7; tech_hi = 7;
	} else if ( technology == 5 ) {  // 5nm FinFET
		tech_lo = 5; tech_hi = 5;
	} else if ( technology < 90 && technology > 65 ) { // 89nm -- 66nm
		tech_lo = 90; tech_hi = 65;
	} else if ( technology < 65 && technology > 45 ) { // 64nm -- 46nm
		tech_lo = 65; tech_hi = 45;
	} else if ( technology < 45 && technology > 32 ) { // 44nm -- 33nm
		tech_lo = 45; tech_hi = 32;
	} else if ( technology < 32 && technology > 22 ) { // 31nm -- 23nm
		tech_lo = 32; tech_hi = 22;
	} else if ( technology < 22 && technology > 16 ) { // 21nm -- 17nm
		tech_lo = 22; tech_hi = 16;
	} else if ( technology < 16 && technology > 14 ) { // 15nm
		tech_lo = 16; tech_hi = 14;
	} else {
		cout << "ERROR: Invalid technology node!" << endl;
		exit(0);
	}

	double Lphy_dram, Lelec_dram;
	double vdd_dram;
	double c_ox_dram, c_fringe_dram, c_junc_dram;
	double I_on_n_dram, I_on_p_dram, I_off_n_dram, I_off_p_dram;
	
	double t_ox_dram, v_th_dram, mobility_eff_dram, Vdsat_dram, c_g_ideal_dram;
	double nmos_effective_resistance_multiplier, n_to_p_eff_curr_drv_ratio, gmp_to_gmn_multiplier_dram;
//    double Rnchannelon_dram, Rpchannelon_dram;

	double vdd_cell, vdd_peri;
	double Lphy, Xj, delta_L, Lelec, t_ox;
	double p_fin, h_fin, t_si;
	double w_fin;	//newly added by Divya.
	double v_th, Vdsat;
	double c_junc, c_junc_sidewall, c_junc_sidewall_gate;
	double c_ox, c_g_ideal, c_fringe, c_gate; //c_gate added newly by Divya
	double I_on_n, I_on_p, I_off_n, I_off_p;
	double Rnchannelon, Rpchannelon;
	double vbit_sense_min;
	double mobility_eff, gmp_to_gmn_multiplier;
	double I_on_n_to_I_on_p_ratio; //newly added by Divya
	double Ioffs[5];

	double vdd, vdd_real, alpha_power_law;	//divya adding for 45-nm
	double curr_logic_scaling_co_eff = 0;//This is based on the reported numbers of Intel Merom 65nm, Penryn45nm and IBM cell 90/65/45 date
	double curr_core_tx_density = 0;//this is density per um^2; 90, ...22nm based on Intel Penryn
	double curr_chip_layout_overhead = 0;
	double curr_macro_layout_overhead = 0;
	double curr_sckt_co_eff = 0;

  
	for (iter = 0; iter <= 1; ++iter) {
		// linear interpolation
		if (iter == 0) {
			tech = tech_lo;
			if (tech_lo == tech_hi) {
				curr_alpha = 1;
			} else {
				curr_alpha = (technology - tech_hi)/(tech_lo - tech_hi);
			}
		} else {
			tech = tech_hi;
			if (tech_lo == tech_hi) {
				break;
			} else {
				curr_alpha = (tech_lo - technology)/(tech_lo - tech_hi);
			}
		}
		
		double lambda_um = (double)tech / 2.0 / 1000.0; // Alireza: lambda in um
/*
		//Divya adding 45-nm technology 23-11-2021
	    if (tech == 45)
	    { //45nm technology-node. Corresponds to year 2010 in ITRS
	      //ITRS HP device type
	    	cout << "45-nm \n";
	      SENSE_AMP_D = .04e-9; // s
	      SENSE_AMP_P = 2.7e-15; // J
	      vdd = 1.0;
	      vdd_real = g_ip->vdd;	//g_ip->specific_hp_vdd ? g_ip->hp_Vdd : vdd;//TODO
	      vdd_cell = vdd_real;
	      alpha_power_law=1.21;
	      Lphy = 0.018;
	      Lelec = 0.01345;
	      t_ox = 0.65e-3;
	      v_th = .18035;
	      c_ox = 3.77e-14;
	      mobility_eff = 266.68 * (1e-2 * 1e6 * 1e-2 * 1e6);
	      Vdsat = 9.38E-2;
	      c_g_ideal = 6.78e-16;
	      c_fringe = 0.05e-15;
	      c_junc = 1e-15;
	      I_on_n = 2046.6e-6*pow((vdd_real-v_th)/(vdd-v_th),alpha_power_law);
	      //There are certain problems with the ITRS PMOS numbers in MASTAR for 45nm. So we are using 65nm values of
	      //n_to_p_eff_curr_drv_ratio and gmp_to_gmn_multiplier for 45nm
	      I_on_p = I_on_n / 2;//This value is fixed arbitrarily but I_on_p is not being used in CACTI
	      nmos_effective_resistance_multiplier = 1.51;
	      n_to_p_eff_curr_drv_ratio = 2.41;
	      gmp_to_gmn_multiplier = 1.38;
	      Rnchannelon = nmos_effective_resistance_multiplier * vdd_real / I_on_n;
	      Rpchannelon = n_to_p_eff_curr_drv_ratio * Rnchannelon;
//	      long_channel_leakage_reduction = 1/3.546;//Using MASTAR, @380K, increase Lgate until Ion reduces to 90%, Ioff(Lgate normal)/Ioff(Lgate long)= 3.74

	      I_off_n = 2.8e-7*pow(vdd_real/(vdd),4); //at 300K
//	      I_g_on_n  = 3.59e-8;//A/micron	//divya removing I_g_on as this is insignificant in FinFETs/NCFETs
		  vbit_sense_min = 0.08;

	      if (ram_cell_tech_type == lp_dram)
	      {
	        //LP-DRAM cell access transistor technology parameters
	        curr_vdd_dram_cell = 1.1;
	        Lphy_dram = 0.078;
	        Lelec = 0.0504;// Assume Lelec is 30% lesser than Lphy for DRAM access and wordline transistors.
	        curr_v_th_dram_access_transistor = 0.44559;
	        width_dram_access_transistor = 0.079;
	        curr_I_on_dram_cell = 36e-6;//A
	        curr_I_off_dram_cell_worst_case_length_temp = 19.5e-12;
	        curr_Wmemcella_dram = width_dram_access_transistor;
	        curr_Wmemcellpmos_dram = 0;
	        curr_Wmemcellnmos_dram  = 0;
	        curr_area_cell_dram = width_dram_access_transistor * Lphy_dram * 10.0;
	        curr_asp_ratio_cell_dram = 1.46;
	        curr_c_dram_cell = 20e-15;

	        //LP-DRAM wordline transistor parameters
	        curr_vpp = 1.5;
	        t_ox_dram = 2.1e-3;
	        v_th_dram = 0.44559;
	        c_ox_dram = 1.41e-14;
	        mobility_eff_dram =   426.30 * (1e-2 * 1e6 * 1e-2 * 1e6);
	        Vdsat_dram = 0.181;
	        c_g_ideal_dram = 1.10e-15;
	        c_fringe_dram = 0.08e-15;
	        c_junc_dram = 1e-15;
	        I_on_n_dram = 456e-6;
	        I_on_p_dram = I_on_n_dram / 2;
	        nmos_effective_resistance_multiplier = 1.65;
	        n_to_p_eff_curr_drv_ratio = 2.05;
	        gmp_to_gmn_multiplier_dram = 0.90;
	        Rnchannelon = nmos_effective_resistance_multiplier * curr_vpp / I_on_n_dram;
	        Rpchannelon = n_to_p_eff_curr_drv_ratio * Rnchannelon;
//	        long_channel_leakage_reduction[3] = 1;
	        I_off_n_dram = 2.54e-11;
	      }
	      else if (ram_cell_tech_type == comm_dram)
	      {
	        //COMM-DRAM cell access transistor technology parameters
	        curr_vdd_dram_cell = 1.1;
	        Lphy_dram = 0.045;
	        Lelec_dram = 0.0298;
	        curr_v_th_dram_access_transistor = 1;
	        width_dram_access_transistor = 0.045;
	        curr_I_on_dram_cell = 20e-6;//A
	        curr_I_off_dram_cell_worst_case_length_temp = 1e-15;
	        curr_Wmemcella_dram = width_dram_access_transistor;
	        curr_Wmemcellpmos_dram = 0;
	        curr_Wmemcellnmos_dram  = 0;
	        curr_area_cell_dram = 6*0.045*0.045;
	        curr_asp_ratio_cell_dram = 1.5;
	        curr_c_dram_cell = 30e-15;

	        //COMM-DRAM wordline transistor parameters
	        curr_vpp = 2.7;
	        t_ox_dram = 4e-3;
	        v_th_dram = 1.0;
	        c_ox_dram = 7.98e-15;
	        mobility_eff_dram = 368.58 * (1e-2 * 1e6 * 1e-2 * 1e6);
	        Vdsat_dram = 0.147;
	        c_g_ideal_dram = 3.59e-16;
	        c_fringe_dram = 0.08e-15;
	        c_junc_dram = 1e-15;
	        I_on_n_dram = 999.4e-6;
	        I_on_p_dram = I_on_n_dram / 2;
	        nmos_effective_resistance_multiplier = 1.69;
	        n_to_p_eff_curr_drv_ratio = 1.95;
	        gmp_to_gmn_multiplier_dram = 0.90;
	        Rnchannelon = nmos_effective_resistance_multiplier * curr_vpp / I_on_n_dram;
	        Rpchannelon = n_to_p_eff_curr_drv_ratio * Rnchannelon;
//	        long_channel_leakage_reduction[3] = 1;
	        I_off_n_dram = 1.31e-14;
	      }

	      //SRAM cell properties
	      curr_Wmemcella_sram = 1.31 * g_ip->F_sz_um;
	      curr_Wmemcellpmos_sram = 1.23 * g_ip->F_sz_um;
	      curr_Wmemcellnmos_sram = 2.08 * g_ip->F_sz_um;
	      curr_area_cell_sram = 146 * g_ip->F_sz_um * g_ip->F_sz_um;
	      curr_asp_ratio_cell_sram = 1.46;
	      //CAM cell properties //TODO: data need to be revisited
	      curr_Wmemcella_cam = 1.31 * g_ip->F_sz_um;
	      curr_Wmemcellpmos_cam = 1.23 * g_ip->F_sz_um;
	      curr_Wmemcellnmos_cam = 2.08 * g_ip->F_sz_um;
	      curr_area_cell_cam = 292 * g_ip->F_sz_um * g_ip->F_sz_um;
	      curr_asp_ratio_cell_cam = 2.92;
	      //Empirical undifferentiated core/FU coefficient
	      curr_logic_scaling_co_eff = 0.7*0.7;
	      curr_core_tx_density      = 1.25;
	      curr_sckt_co_eff           = 1.1387;
	      curr_chip_layout_overhead  = 1.2;//die measurement results based on Niagara 1 and 2
	      curr_macro_layout_overhead = 1.1;//EDA placement and routing tool rule of thumb

	      g_tp.Vbit_sense_min = vbit_sense_min;

	      g_tp.peri_global.Vdd       += curr_alpha * vdd_real;//real vdd, user defined or itrs
	      g_tp.peri_global.Vth       += curr_alpha * v_th;
	      g_tp.peri_global.t_ox      += curr_alpha * t_ox;
	      g_tp.peri_global.C_ox      += curr_alpha * c_ox;
	      g_tp.peri_global.C_g_ideal += curr_alpha * c_g_ideal;
	      g_tp.peri_global.C_fringe  += curr_alpha * c_fringe;
	      g_tp.peri_global.C_junc    += curr_alpha * c_junc;
	      g_tp.peri_global.C_junc_sidewall = 0.25e-15;  // F/micron
	      g_tp.peri_global.l_phy     += curr_alpha * Lphy;
	      g_tp.peri_global.l_elec    += curr_alpha * Lelec;
	      g_tp.peri_global.I_on_n    += curr_alpha * I_on_n;
	      g_tp.peri_global.R_nch_on  += curr_alpha * Rnchannelon;
	      g_tp.peri_global.R_pch_on  += curr_alpha * Rpchannelon;
	      g_tp.peri_global.n_to_p_eff_curr_drv_ratio
	        += curr_alpha * n_to_p_eff_curr_drv_ratio;
	      g_tp.peri_global.long_channel_leakage_reduction
	        += curr_alpha * 0;//long_channel_leakage_reduction;
	      g_tp.peri_global.I_off_n   += curr_alpha * I_off_n; //*pow(g_tp.peri_global.Vdd/g_tp.peri_global.Vdd_default,3);//Consider the voltage change may affect the current density as well. TODO: polynomial curve-fitting based on MASTAR may not be accurate enough
	      g_tp.peri_global.I_off_p   += curr_alpha * I_off_n; //*pow(g_tp.peri_global.Vdd/g_tp.peri_global.Vdd_default,3);//To mimic the Vdd effect on Ioff (for the same device, dvs should not change default Ioff---only changes if device is different?? but MASTAR shows different results)
//	      g_tp.peri_global.I_g_on_n   += curr_alpha * I_g_on_n[g_ip->temp - 300];
//	      g_tp.peri_global.I_g_on_p   += curr_alpha * I_g_on_n[g_ip->temp - 300];
	      gmp_to_gmn_multiplier_periph_global += curr_alpha * gmp_to_gmn_multiplier;

	      g_tp.sram_cell.Vdd       += curr_alpha * vdd_real;
	      g_tp.sram_cell.Vth       += curr_alpha * v_th;
	      g_tp.sram_cell.l_phy     += curr_alpha * Lphy;
	      g_tp.sram_cell.l_elec    += curr_alpha * Lelec;
	      g_tp.sram_cell.t_ox      += curr_alpha * t_ox;
	      g_tp.sram_cell.C_g_ideal += curr_alpha * c_g_ideal;
	      g_tp.sram_cell.C_fringe  += curr_alpha * c_fringe;
	      g_tp.sram_cell.C_junc    += curr_alpha * c_junc;
	      g_tp.sram_cell.C_junc_sidewall = 0.25e-15;  // F/micron
	      g_tp.sram_cell.I_on_n    += curr_alpha * I_on_n;
	      g_tp.sram_cell.R_nch_on  += curr_alpha * Rnchannelon;
	      g_tp.sram_cell.R_pch_on  += curr_alpha * Rpchannelon;
	      g_tp.sram_cell.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
	      g_tp.sram_cell.long_channel_leakage_reduction += curr_alpha * 0;	//long_channel_leakage_reduction;
	      g_tp.sram_cell.I_off_n   += curr_alpha * I_off_n;//**pow(g_tp.sram_cell.Vdd/g_tp.sram_cell.Vdd_default,4);
	      g_tp.sram_cell.I_off_p   += curr_alpha * I_off_n;//**pow(g_tp.sram_cell.Vdd/g_tp.sram_cell.Vdd_default,4);
//	      g_tp.sram_cell.I_g_on_n   += curr_alpha * I_g_on_n[g_ip->temp - 300];
//	      g_tp.sram_cell.I_g_on_p   += curr_alpha * I_g_on_n[g_ip->temp - 300];

	      g_tp.cam_cell.Vdd       += curr_alpha * vdd_real;
	      g_tp.cam_cell.l_phy     += curr_alpha * Lphy;
	      g_tp.cam_cell.l_elec    += curr_alpha * Lelec;
	      g_tp.cam_cell.t_ox      += curr_alpha * t_ox;
	      g_tp.cam_cell.Vth       += curr_alpha * v_th;
	      g_tp.cam_cell.C_g_ideal += curr_alpha * c_g_ideal;
	      g_tp.cam_cell.C_fringe  += curr_alpha * c_fringe;
	      g_tp.cam_cell.C_junc    += curr_alpha * c_junc;
	      g_tp.cam_cell.C_junc_sidewall = 0.25e-15;  // F/micron
	      g_tp.cam_cell.I_on_n    += curr_alpha * I_on_n;
	      g_tp.cam_cell.R_nch_on  += curr_alpha * Rnchannelon;
	      g_tp.cam_cell.R_pch_on  += curr_alpha * Rpchannelon;
	      g_tp.cam_cell.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
	      g_tp.cam_cell.long_channel_leakage_reduction += curr_alpha * 0;	//long_channel_leakage_reduction;
	      g_tp.cam_cell.I_off_n   += curr_alpha * I_off_n;//*pow(g_tp.cam_cell.Vdd/g_tp.cam_cell.Vdd_default,4);
	      g_tp.cam_cell.I_off_p   += curr_alpha * I_off_n;//**pow(g_tp.cam_cell.Vdd/g_tp.cam_cell.Vdd_default,4);
//	      g_tp.cam_cell.I_g_on_n   += curr_alpha * I_g_on_n[g_ip->temp - 300];
//	      g_tp.cam_cell.I_g_on_p   += curr_alpha * I_g_on_n[g_ip->temp - 300];

	    }	//end of 45-nm data
*/
    // Standard 14nm (gate length) Planar CMOS based on TCAD.
    // Source: Shuang Chen, USC.
    if (tech == 14 && !g_ip->is_finfet) {
      Lphy_dram = 0.014;
      curr_vdd_dram_cell = ((g_ip->is_near_threshold) ? 0.55 : 0.8);
      c_ox_dram = 3.52e-14;
      c_fringe_dram = 0.8e-16;
      c_junc_dram = 0.5e-15;
      I_on_n_dram = ((g_ip->is_near_threshold) ? 1.155e-04 : 8.367e-04);
      I_on_p_dram = ((g_ip->is_near_threshold) ? 8.618e-05 : 5.012e-04);
      I_off_n_dram = ((g_ip->is_near_threshold) ? 3.282e-08 : 9.662e-08);
      I_off_p_dram = ((g_ip->is_near_threshold) ? 3.460e-08 : 1.095e-07);
    }
    
    // Standard 7nm (gate length) FinFET based on TCAD.
    // Source: Shuang Chen, USC.
    if (tech == 7 && g_ip->is_finfet) {
      Lphy_dram = 0.007;
      curr_vdd_dram_cell = ((g_ip->is_near_threshold) ? 0.3 : 0.45);
      c_ox_dram = 4.73e-14;
      c_fringe_dram = 0.8e-16;
      c_junc_dram = 0.5e-15;
		I_on_n_dram = ((g_ip->is_near_threshold) ? 2.845e-04 : 1.716e-03);
      I_on_p_dram = ((g_ip->is_near_threshold) ? 2.610e-04 : 1.075e-03);
      I_off_n_dram = ((g_ip->is_near_threshold) ? 6.355e-08 : 6.890e-08);
      I_off_p_dram = ((g_ip->is_near_threshold) ? 1.027e-07 : 1.040e-07);
    }

	    if(tech == 14 && g_ip->is_finfet && !g_ip->use_device_xml)//14-nm
		{
//    		cout << "technology.cc:: 14nm , finfet: " << g_ip->is_finfet << ", vdd:" << g_ip->vdd << endl;
			//-------------------- cell parameters begin --------------------------
			Lphy 	= 0.02;	//20-nm represented in um
			Xj 		= 0;

			//Divya 14-11-2021
			//Fixing geometries to 14-nm Fin/NC-FinFET transistor type as we working only for it

			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if(g_ip->is_finfet) {
				if(g_ip->is_ncfet)	//NCFET
					t_ox = 0.00043;	//0.43nm represented in um
				else	//Finfet
					t_ox = 0.001;	//1nm represented in um
			}

			//FinFET and NCFET have same values for below parameters
			if ( g_ip->is_finfet ) {
				t_si 	= 0.008;	//8-nm
				h_fin 	= 0.042;	//42nm represented in um
				p_fin 	= 0.042; 	//42nm represented in um
				w_fin 	= 0.008;	//8-nm
			}

			vdd_cell = g_ip->vdd;

			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if ( g_ip->is_finfet ) {
				if(g_ip->is_ncfet)	//NCFET
				{
					if(vdd_cell == 0.2)
						v_th = 0.202;
					else if(vdd_cell == 0.3)
						v_th = 0.201;
					else if(vdd_cell == 0.4)
						v_th = 0.205;
					else if(vdd_cell == 0.5)
						v_th = 0.21;
					else if(vdd_cell == 0.6)
						v_th = 0.215;
					else if(vdd_cell == 0.7)
						v_th = 0.2195;
					else if(vdd_cell == 0.8)
						v_th = 0.2245;
				}
				else //FinFET
				{
					if(vdd_cell == 0.2)
						v_th = 0.262;
					else if(vdd_cell == 0.3)
						v_th = 0.261;
					else if(vdd_cell == 0.4)
						v_th = 0.2565;
					else if(vdd_cell == 0.5)
						v_th = 0.251;
					else if(vdd_cell == 0.6)
						v_th = 0.2455;
					else if(vdd_cell == 0.7)
						v_th = 0.24;
					else if(vdd_cell == 0.8)
						v_th = 0.235;
				}
			}

			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if ( g_ip->is_finfet ) {
				if(g_ip->is_ncfet)	//NCFET
				{
					c_ox = 2.9e-13;	//f/um2
					c_fringe = 2.29891e-16; //f/um
					c_junc = 5.0e-16; //f/um2
					c_junc_sidewall = 5.0e-16; //f/um
					c_junc_sidewall_gate = 0;

					if(vdd_cell == 0.2)
						c_gate = 2.53804e-16;	//f/um
					else if(vdd_cell == 0.3)
						c_gate = 6.09783e-16;
					else if(vdd_cell == 0.4)
						c_gate = 6.79891e-16;
					else if(vdd_cell == 0.5)
						c_gate = 7.33696e-16;
					else if(vdd_cell == 0.6)
						c_gate = 7.760874e-16;
					else if(vdd_cell == 0.7)
						c_gate = 8.11957e-16;
					else if(vdd_cell == 0.8)
						c_gate = 8.375e-16;
				}
				else //FinFET
				{
					c_ox = 3.67e-14;	//f/um2
					c_fringe = 2.29891e-16; //f/um
					c_junc = 5.0e-16; //f/um2
					c_junc_sidewall = 5.0e-16; //f/um
					c_junc_sidewall_gate = 0;

					if(vdd_cell == 0.2)
						c_gate = 4.18478e-18;
					else if(vdd_cell == 0.3)
						c_gate = 5.49457e-17;
					else if(vdd_cell == 0.4)
						c_gate = 1.375e-16;
					else if(vdd_cell == 0.5)
						c_gate = 1.85326e-16;
					else if(vdd_cell == 0.6)
						c_gate = 2.14674e-16;
					else if(vdd_cell == 0.7)
						c_gate = 2.364133e-16;
					else if(vdd_cell == 0.8)
						c_gate = 2.52717e-16;
				}
			}

			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if ( g_ip->is_finfet ) {
				if(g_ip->is_ncfet)	//NCFET
				{
					SENSE_AMP_D = 3.101e-12;
					SENSE_AMP_P = 3.630e-19;
				}
				else //FinFET
				{
					SENSE_AMP_D = 3.101e-12;
					SENSE_AMP_P = 3.630e-19;
				}
			}

			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if ( g_ip->is_finfet ) {
				if(g_ip->is_ncfet)	//NCFET
				{
					if(vdd_cell == 0.2)
					{
						I_on_n = 4.456522e-06;	// Amp/um
						I_on_p = 3.043478e-06;	// Amp/um
						I_off_n = 1.51087e-09;	// Amp/um
						I_off_p = 2.163043e-09;	// Amp/um
					}
					else if(vdd_cell == 0.3)
					{
						I_on_n = 4.315217e-05;
						I_on_p = 3.75e-05;
						I_off_n = 1.304348e-09;
						I_off_p = 1.771739e-09;
					}
					else if(vdd_cell == 0.4)
					{
						I_on_n = 1.6413e-04;
						I_on_p = 1.59783e-04;
						I_off_n = 1.119565e-09;
						I_off_p = 1.456522e-09;
					}
					else if(vdd_cell == 0.5)
					{
						I_on_n = 3.82609e-04;
						I_on_p = 3.53261e-04;
						I_off_n = 1.0e-09;
						I_off_p = 1.184783e-09;
					}
					else if(vdd_cell == 0.6)
					{
						I_on_n = 6.59783e-04;
						I_on_p = 5.81522e-04;
						I_off_n = 8.119565e-10;
						I_off_p = 1.0e-09;
					}
					else if(vdd_cell == 0.7)
					{
						I_on_n = 9.65217e-04;
						I_on_p = 8.09783e-04;
						I_off_n = 6.880435e-10;
						I_off_p = 7.836957e-10;
					}
					else if(vdd_cell == 0.8)
					{
						I_on_n = 1.206522e-03;
						I_on_p = 1.047826e-03;
						I_off_n = 5.836957e-10;
						I_off_p = 6.39565e-10;
					}
					I_on_n_to_I_on_p_ratio = 1.4642857143;
				}
				else //FinFET
				{
					if(vdd_cell == 0.2)
					{
						I_on_n = 7.728261e-07;
						I_on_p = 6.586957e-07;
						I_off_n = 1.489133e-09;
						I_off_p = 1.532609e-09;
					}
					else if(vdd_cell == 0.3)
					{
						I_on_n = 1.3913e-05;
						I_on_p = 1.1413e-05;
						I_off_n = 2.0e-09;
						I_off_p = 2.0e-09;
					}
					else if(vdd_cell == 0.4)
					{
						I_on_n = 7.663043e-05;
						I_on_p = 6.456522e-05;
						I_off_n = 2.565217e-09;
						I_off_p = 2.5e-09;
					}
					else if(vdd_cell == 0.5)
					{
						I_on_n = 1.91304e-04;
						I_on_p = 1.66304e-04;
						I_off_n = 3.304348e-09;
						I_off_p = 3.195652e-09;
					}
					else if(vdd_cell == 0.6)
					{
						I_on_n = 3.40217e-04;
						I_on_p = 3.02174e-04;
						I_off_n = 4.217391e-09;
						I_off_p = 4.054348e-09;
					}
					else if(vdd_cell == 0.7)
					{
						I_on_n = 5.07609e-04;
						I_on_p = 4.57609e-04;
						I_off_n = 5.336957e-09;
						I_off_p = 5.130435e-09;
					}
					else if(vdd_cell == 0.8)
					{
						I_on_n = 6.86957e-04;
						I_on_p = 6.23913e-04;
						I_off_n = 6.684783e-09;
						I_off_p = 6.478261e-09;
					}
					I_on_n_to_I_on_p_ratio = 1.219047619;
				}
			}

			/***** Alireza - BEGIN *****/
			if (g_ip->is_finfet) {
				vbit_sense_min = 0.04;
				g_tp.sram_cell.P_fin   += curr_alpha * p_fin;
				g_tp.sram_cell.H_fin   += curr_alpha * h_fin;
				g_tp.sram_cell.T_si    += curr_alpha * t_si;
				g_tp.sram_cell.W_fin   += curr_alpha * w_fin;
				// FinFET-based SRAM cell properties:
				double sram_cell_height, sram_cell_width;
				sram_cell_height = g_ip->sram_cell_design.calc_height(lambda_um);
				sram_cell_width = g_ip->sram_cell_design.calc_width(lambda_um, p_fin, t_si);
				int n[5];
				g_ip->sram_cell_design.getNfins(n);

				curr_Wmemcella_sram      = n[0] * (2*h_fin + w_fin); //w_fin;
				curr_Wmemcellpmos_sram   = n[1] * (2*h_fin + w_fin); //w_fin;
				curr_Wmemcellnmos_sram   = n[2] * (2*h_fin + w_fin); //w_fin;
				curr_Wmemcellrdiso_sram  = n[3] * (2*h_fin + w_fin); //w_fin;
				curr_Wmemcellrda_sram    = n[4] * (2*h_fin + w_fin); //w_fin;
				curr_area_cell_sram      = sram_cell_height * sram_cell_width;
				curr_asp_ratio_cell_sram = sram_cell_height / sram_cell_width;

				//CAM cell properties //TODO: data need to be revisited
				//divya added 12-11-2021
				curr_Wmemcella_cam 		= curr_Wmemcella_sram;
				curr_Wmemcellpmos_cam 	= curr_Wmemcellpmos_sram;
				curr_Wmemcellnmos_cam 	= curr_Wmemcellnmos_sram;
				curr_area_cell_cam 		= 2*curr_area_cell_sram;	//divya added based on ratios found in mcpat cacti
				curr_asp_ratio_cell_cam = 2*curr_asp_ratio_cell_sram; //divya added based on ratios found in mcpat cacti

			} else {	//cmos
				vbit_sense_min = 0.08;
				// CMOS-based SRAM cell properties:
				if ( g_ip->sram_cell_design.getType() == std_6T ) {
					curr_Wmemcella_sram      = 1.31 * g_ip->F_sz_um;
					curr_Wmemcellpmos_sram   = 1.23 * g_ip->F_sz_um;
					curr_Wmemcellnmos_sram   = 2.08 * g_ip->F_sz_um;
					curr_area_cell_sram      = 146 * g_ip->F_sz_um * g_ip->F_sz_um;
					curr_asp_ratio_cell_sram = 1.46;
				} else if ( g_ip->sram_cell_design.getType() == std_8T ) {
					// Source: Chang et al., "Stable SRAM cell design for the 32 nm node and beyond," VLSI Symposia 2005.
					curr_Wmemcella_sram      = 1.0 * g_ip->F_sz_um;
					curr_Wmemcellpmos_sram   = 1.0 * g_ip->F_sz_um;
					curr_Wmemcellnmos_sram   = 1.0 * g_ip->F_sz_um;
					curr_Wmemcellrda_sram    = 1.0 * g_ip->F_sz_um;
					curr_Wmemcellrdiso_sram  = 3.5 * g_ip->F_sz_um;
					curr_area_cell_sram      = 195 * g_ip->F_sz_um * g_ip->F_sz_um;
					curr_asp_ratio_cell_sram = 0.36;
				} else {
					cout << "ERROR: Invalid SRAM cell type in technology.cc!\n";
					exit(0);
				}
			}

			g_tp.Vbit_sense_min = vbit_sense_min;

			delta_L = (g_ip->is_finfet) ? (2*0.8*Xj) : (0.8*Xj);
	//		c_g_ideal = Lphy * c_ox;	//Divya :: c_g_ideal changes with voltage for NCFET, this is no longer valid
			c_g_ideal = (g_ip->is_finfet) ? c_gate : (Lphy * c_ox);	//Divya added this . (in F, not in F/um)

			Lelec = Lphy - delta_L;
			if ( Lelec <=0 ) {
				cout << "ERROR: Lelec (ram_cell) is not a positive value! Please check the Lphy or the Xj value.\n";
				exit(0);
			}
			n_to_p_eff_curr_drv_ratio = I_on_n_to_I_on_p_ratio; //1.219047619; //Finfet //I_on_n / I_on_p; (original) //Divya replaced this value with Max(I_on_n/I_on_p for all voltages) //1.4642857143 //NCFET
			Rnchannelon = vdd_cell / I_on_n;
			Rpchannelon = vdd_cell / I_on_p;
			g_tp.sram_cell.Vdd       += curr_alpha * vdd_cell;
			g_tp.sram_cell.l_phy     += curr_alpha * Lphy;
			g_tp.sram_cell.l_elec    += curr_alpha * Lelec;
			g_tp.sram_cell.t_ox      += curr_alpha * t_ox;
			g_tp.sram_cell.Vth       += curr_alpha * v_th;
			g_tp.sram_cell.C_g_ideal += curr_alpha * c_g_ideal;
			g_tp.sram_cell.C_fringe  += curr_alpha * c_fringe;
			g_tp.sram_cell.C_junc    += curr_alpha * c_junc;
			g_tp.sram_cell.C_junc_sidewall = c_junc_sidewall;
			g_tp.sram_cell.I_on_n    += curr_alpha * I_on_n;
			g_tp.sram_cell.I_on_p    += curr_alpha * I_on_p;
			g_tp.sram_cell.I_off_n   += curr_alpha * I_off_n;
			g_tp.sram_cell.I_off_p   += curr_alpha * I_off_p;
			g_tp.sram_cell.R_nch_on  += curr_alpha * Rnchannelon;
			g_tp.sram_cell.R_pch_on  += curr_alpha * Rpchannelon;
			g_tp.sram_cell.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
			/****** Alireza - END ******/
			//divya adding 12-11-2021
			g_tp.cam_cell.Vdd       += curr_alpha * vdd_cell;
			g_tp.cam_cell.l_phy     += curr_alpha * Lphy;
			g_tp.cam_cell.l_elec    += curr_alpha * Lelec;
			g_tp.cam_cell.t_ox      += curr_alpha * t_ox;
			g_tp.cam_cell.Vth       += curr_alpha * v_th;
			g_tp.cam_cell.C_g_ideal += curr_alpha * c_g_ideal;
			g_tp.cam_cell.C_fringe  += curr_alpha * c_fringe;
			g_tp.cam_cell.C_junc    += curr_alpha * c_junc;
			g_tp.cam_cell.C_junc_sidewall = c_junc_sidewall;
			g_tp.cam_cell.I_on_n    += curr_alpha * I_on_n;
			g_tp.cam_cell.I_on_p    += curr_alpha * I_on_p;
			g_tp.cam_cell.R_nch_on  += curr_alpha * Rnchannelon;
			g_tp.cam_cell.R_pch_on  += curr_alpha * Rpchannelon;
			g_tp.cam_cell.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
			g_tp.cam_cell.I_off_n   += curr_alpha * I_off_n;//*pow(g_tp.cam_cell.Vdd/g_tp.cam_cell.Vdd_default,4);
			g_tp.cam_cell.I_off_p   += curr_alpha * I_off_n;//**pow(g_tp.cam_cell.Vdd/g_tp.cam_cell.Vdd_default,4);


			//-------------------- cell parameters end ----------------------------

			//-------------------- peripheral parameters begin --------------------
			Lphy = 0.02;	//20-nm represented in um
			Xj = 0;

			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if(g_ip->is_finfet) {
				if(g_ip->is_ncfet)	//NCFET
					t_ox = 0.00043;	//0.43nm represented in um
				else	//Finfet
					t_ox = 0.001;	//1nm represented in um
			}

			//FinFET and NCFET have same values for below parameters
			if ( g_ip->is_finfet ) {
				t_si = 0.008;	//8-nm
				h_fin = 0.042;	//42nm represented in um
				p_fin = 0.042; 	//42nm represented in um
				w_fin = 0.008;	//8-nm
			}

			vdd_peri = g_ip->vdd;
			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if ( g_ip->is_finfet ) {
				if(g_ip->is_ncfet)	//NCFET
				{
					if(vdd_peri == 0.2) {
						v_th = 0.202;
						Vdsat= 0.0569;
					} else if(vdd_peri == 0.3) {
						v_th = 0.201;
						Vdsat= 0.0782;
					} else if(vdd_peri == 0.4) {
						v_th = 0.205;
						Vdsat= 0.1315;
					} else if(vdd_peri == 0.5) {
						v_th = 0.21;
						Vdsat= 0.21;
					} else if(vdd_peri == 0.6) {
						v_th = 0.215;
						Vdsat= 0.3015;
					} else if(vdd_peri == 0.7) {
						v_th = 0.2195;
						Vdsat= 0.3995;
					} else if(vdd_peri == 0.8) {
						v_th = 0.2245;
						Vdsat= 0.5005;
					}
				}
				else //FinFET
				{
					if(vdd_peri == 0.2) {
						v_th = 0.262;
						Vdsat= 0.048;
					} else if(vdd_peri == 0.3) {
						v_th = 0.261;
						Vdsat= 0.05675;
					} else if(vdd_peri == 0.4) {
						v_th = 0.2565;
						Vdsat= 0.08705;
					} else if(vdd_peri == 0.5) {
						v_th = 0.251;
						Vdsat= 0.132;
					} else if(vdd_peri == 0.6) {
						v_th = 0.2455;
						Vdsat= 0.1845;
					} else if(vdd_peri == 0.7) {
						v_th = 0.24;
						Vdsat= 0.242;
					} else if(vdd_peri == 0.8) {
						v_th = 0.235;
						Vdsat= 0.3025;
					}
				}
			}

			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if ( g_ip->is_finfet ) {
				if(g_ip->is_ncfet)	//NCFET
				{
					c_ox 					= 2.9e-13;	//f/um2
					c_fringe 				= 2.29891e-16; //f/um
					c_junc 					= 5.0e-16; //f/um2
					c_junc_sidewall 		= 5.0e-16; //f/um
					c_junc_sidewall_gate 	= 0;
					mobility_eff 			= 242e8;
					gmp_to_gmn_multiplier 	= 1.38;

					if(vdd_peri == 0.2)
						c_gate = 2.53804e-16;	//f/um
					else if(vdd_peri == 0.3)
						c_gate = 6.09783e-16;
					else if(vdd_peri == 0.4)
						c_gate = 6.79891e-16;
					else if(vdd_peri == 0.5)
						c_gate = 7.33696e-16;
					else if(vdd_peri == 0.6)
						c_gate = 7.760874e-16;
					else if(vdd_peri == 0.7)
						c_gate = 8.11957e-16;
					else if(vdd_peri == 0.8)
						c_gate = 8.375e-16;
				}
				else //FinFET
				{
					c_ox 					= 3.67e-14;	//f/um2
					c_fringe 				= 2.29891e-16; //f/um
					c_junc 					= 5.0e-16; //f/um2
					c_junc_sidewall 		= 5.0e-16; //f/um
					c_junc_sidewall_gate 	= 0;
					mobility_eff 			= 242e8;
					gmp_to_gmn_multiplier 	= 1.38;

					if(vdd_peri == 0.2)
						c_gate = 4.18478e-18;
					else if(vdd_peri == 0.3)
						c_gate = 5.49457e-17;
					else if(vdd_peri == 0.4)
						c_gate = 1.375e-16;
					else if(vdd_peri == 0.5)
						c_gate = 1.85326e-16;
					else if(vdd_peri == 0.6)
						c_gate = 2.14674e-16;
					else if(vdd_peri == 0.7)
						c_gate = 2.364133e-16;
					else if(vdd_peri == 0.8)
						c_gate = 2.52717e-16;
				}
			}
			//Divya : end

			//for finfet or cmos check. finfets can be FinFET or NCFET which is captured in is_ncfet
			if ( g_ip->is_finfet ) {
				if(g_ip->is_ncfet)	//NCFET
				{
					if(vdd_peri == 0.2)
					{
						I_on_n = 4.456522e-06;	// Amp/um
						I_on_p = 3.043478e-06;	// Amp/um
						I_off_n = 1.51087e-09;	// Amp/um
						I_off_p = 2.163043e-09;	// Amp/um
					}
					else if(vdd_peri == 0.3)
					{
						I_on_n = 4.315217e-05;
						I_on_p = 3.75e-05;
						I_off_n = 1.304348e-09;
						I_off_p = 1.771739e-09;
					}
					else if(vdd_peri == 0.4)
					{
						I_on_n = 1.6413e-04;
						I_on_p = 1.59783e-04;
						I_off_n = 1.119565e-09;
						I_off_p = 1.456522e-09;
					}
					else if(vdd_peri == 0.5)
					{
						I_on_n = 3.82609e-04;
						I_on_p = 3.53261e-04;
						I_off_n = 1.0e-09;
						I_off_p = 1.184783e-09;
					}
					else if(vdd_peri == 0.6)
					{
						I_on_n = 6.59783e-04;
						I_on_p = 5.81522e-04;
						I_off_n = 8.119565e-10;
						I_off_p = 1.0e-09;
					}
					else if(vdd_peri == 0.7)
					{
						I_on_n = 9.65217e-04;
						I_on_p = 8.09783e-04;
						I_off_n = 6.880435e-10;
						I_off_p = 7.836957e-10;
					}
					else if(vdd_peri == 0.8)
					{
						I_on_n = 1.206522e-03;
						I_on_p = 1.047826e-03;
						I_off_n = 5.836957e-10;
						I_off_p = 6.39565e-10;
					}
					I_on_n_to_I_on_p_ratio = 1.4642857143;
				}
				else //FinFET
				{
					if(vdd_peri == 0.2)
					{
						I_on_n = 7.728261e-07;
						I_on_p = 6.586957e-07;
						I_off_n = 1.489133e-09;
						I_off_p = 1.532609e-09;
					}
					else if(vdd_peri == 0.3)
					{
						I_on_n = 1.3913e-05;
						I_on_p = 1.1413e-05;
						I_off_n = 2.0e-09;
						I_off_p = 2.0e-09;
					}
					else if(vdd_peri == 0.4)
					{
						I_on_n = 7.663043e-05;
						I_on_p = 6.456522e-05;
						I_off_n = 2.565217e-09;
						I_off_p = 2.5e-09;
					}
					else if(vdd_peri == 0.5)
					{
						I_on_n = 1.91304e-04;
						I_on_p = 1.66304e-04;
						I_off_n = 3.304348e-09;
						I_off_p = 3.195652e-09;
					}
					else if(vdd_peri == 0.6)
					{
						I_on_n = 3.40217e-04;
						I_on_p = 3.02174e-04;
						I_off_n = 4.217391e-09;
						I_off_p = 4.054348e-09;
					}
					else if(vdd_peri == 0.7)
					{
						I_on_n = 5.07609e-04;
						I_on_p = 4.57609e-04;
						I_off_n = 5.336957e-09;
						I_off_p = 5.130435e-09;
					}
					else if(vdd_peri == 0.8)
					{
						I_on_n = 6.86957e-04;
						I_on_p = 6.23913e-04;
						I_off_n = 6.684783e-09;
						I_off_p = 6.478261e-09;
					}
					I_on_n_to_I_on_p_ratio = 1.219047619;
				}
			}

	        //Empirical undifferetiated core/FU coefficient
	        curr_logic_scaling_co_eff = 0.7*0.7*0.7*0.7*0.7;	//at 16-nm cmos
	        curr_core_tx_density      = 1.25/0.7/0.7/0.7;		//at 16-nm cmos

//	        curr_logic_scaling_co_eff = 0.7*0.7*0.7*0.7*0.7*0.7;
//	        curr_core_tx_density      = 1.25/0.7/0.7/0.7/0.7;

	        curr_sckt_co_eff           = 1.1296;
	        curr_chip_layout_overhead  = 1.2;//die measurement results based on Niagara 1 and 2
	        curr_macro_layout_overhead = 1.1;//EDA placement and routing tool rule of thumb
/*
			//Empirical undifferetiated core/FU coefficient
			curr_logic_scaling_co_eff 	= 1.0;
			curr_core_tx_density      	= 1.0;
			curr_sckt_co_eff           	= 1.0;
			curr_chip_layout_overhead  	= 1.0;//die measurement results based on Niagara 1 and 2
			curr_macro_layout_overhead 	= 1.0;//EDA placement and routing tool rule of thumb
*/
			if (g_ip->is_finfet) {
				g_tp.peri_global.P_fin += curr_alpha * p_fin;
				g_tp.peri_global.H_fin += curr_alpha * h_fin;
				g_tp.peri_global.T_si  += curr_alpha * t_si;
				g_tp.peri_global.W_fin += curr_alpha * w_fin;
			}
			c_g_ideal = c_gate;	// Divya modified this to include data given (in F, not in F/um)

			delta_L = (g_ip->is_finfet) ? (2*0.8*Xj) : (0.8*Xj);

			Lelec = Lphy - delta_L;
			if ( Lelec <= 0 ) {
				cout << "ERROR: Lelec (peri_global) is not a positive value! Please check the Lphy or the Xj value.\n";
				exit(0);
			}
			n_to_p_eff_curr_drv_ratio = I_on_n_to_I_on_p_ratio; //Divya added; //1.219047619; //Finfet //I_on_n / I_on_p; (original) //Divya replaced this value with Max(I_on_n/I_on_p for all voltages) //1.4642857143 //NCFET
			Rnchannelon = vdd_peri / I_on_n;
			Rpchannelon = vdd_peri / I_on_p;
			g_tp.peri_global.Vdd       += curr_alpha * vdd_peri;
			g_tp.peri_global.t_ox      += curr_alpha * t_ox;
			g_tp.peri_global.Vth       += curr_alpha * v_th;
			g_tp.peri_global.C_ox      += curr_alpha * c_ox;
			g_tp.peri_global.C_g_ideal += curr_alpha * c_g_ideal;
			g_tp.peri_global.C_fringe  += curr_alpha * c_fringe;
			g_tp.peri_global.C_junc    += curr_alpha * c_junc;
			g_tp.peri_global.C_junc_sidewall = c_junc_sidewall;
			g_tp.peri_global.l_phy     += curr_alpha * Lphy;
			g_tp.peri_global.l_elec    += curr_alpha * Lelec;
			g_tp.peri_global.I_on_n    += curr_alpha * I_on_n;
			g_tp.peri_global.I_off_n   += curr_alpha * I_off_n;
			g_tp.peri_global.I_off_p   += curr_alpha * I_off_p;
			g_tp.peri_global.R_nch_on  += curr_alpha * Rnchannelon;
			g_tp.peri_global.R_pch_on  += curr_alpha * Rpchannelon;
			g_tp.peri_global.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
			gmp_to_gmn_multiplier_periph_global += curr_alpha * gmp_to_gmn_multiplier;

        } else if (g_ip->use_device_xml) {
          if (tech_lo != tech_hi) { cerr << "ERROR: XML device path needs an exact node." << endl; exit(1); }
		//-------------------- cell parameters begin --------------------------
		//---------- Majid - BEGIN ----------
		char temp_var[1000];
		XMLNode root_node, geometry_node, voltages_node, cap_node, senseAmp_node;
		XMLNode NMOS_ONcurrents_node, PMOS_ONcurrents_node, NMOS_OFFcurrents_node, PMOS_OFFcurrents_node;
		
		if ( is_tag ) {
			root_node = XMLNode::openFileHelper(g_ip->tag_array_cell_tech_file,"device_definition");
		} else {
			root_node = XMLNode::openFileHelper(g_ip->data_array_cell_tech_file,"device_definition");
		}
		
		geometry_node = root_node.getChildNode("geometries");
		strcpy(temp_var,geometry_node.getChildNode("Lphy").getText(0));
		sscanf(temp_var, "%lf", &(Lphy));
		strcpy(temp_var,geometry_node.getChildNode("Xj").getText(0));
		sscanf(temp_var, "%lf", &(Xj));
		strcpy(temp_var,geometry_node.getChildNode("t_ox").getText(0));
		sscanf(temp_var, "%lf", &(t_ox));
		if ( g_ip->is_finfet ) {
			strcpy(temp_var,geometry_node.getChildNode("FinFET").getChildNode("t_si").getText(0));
			sscanf(temp_var, "%lf", &(t_si));
			strcpy(temp_var,geometry_node.getChildNode("FinFET").getChildNode("h_fin").getText(0));
			sscanf(temp_var, "%lf", &(h_fin));
			if ( !geometry_node.getChildNode("FinFET").getChildNode("p_fin").isEmpty() ) {
				strcpy(temp_var,geometry_node.getChildNode("FinFET").getChildNode("p_fin").getText(0));
				sscanf(temp_var, "%lf", &(p_fin));
			} else {
				p_fin = (2 * lambda_um) + t_si;
			}
		}
		
		w_fin = g_ip->is_finfet ? t_si : 0;
		voltages_node = root_node.getChildNode("voltages");
		strcpy(temp_var,voltages_node.getChildNode("v_th").getText(0));
		sscanf(temp_var, "%lf", &(v_th));
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,voltages_node.getChildNode("vdd").getChildNode("near_threshold").getText(0));
			sscanf(temp_var, "%lf", &(vdd_cell));
		} else {
			strcpy(temp_var,voltages_node.getChildNode("vdd").getChildNode("super_threshold").getText(0));
			sscanf(temp_var, "%lf", &(vdd_cell));
		}
		
		cap_node = root_node.getChildNode("capacitances");
		strcpy(temp_var,cap_node.getChildNode("c_ox").getText(0));
		sscanf(temp_var, "%lf", &(c_ox));
		strcpy(temp_var,cap_node.getChildNode("c_junc_sidewall").getText(0));
		sscanf(temp_var, "%lf", &(c_junc_sidewall));
		strcpy(temp_var,cap_node.getChildNode("c_junc_sidewall_gate").getText(0));
		sscanf(temp_var, "%lf", &(c_junc_sidewall_gate));
		strcpy(temp_var,cap_node.getChildNode("c_junc").getText(0));
		sscanf(temp_var, "%lf", &(c_junc));
		strcpy(temp_var,cap_node.getChildNode("c_fringe").getText(0));
		sscanf(temp_var, "%lf", &(c_fringe));
		
		senseAmp_node = root_node.getChildNode("sense_amplifier");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,senseAmp_node.getChildNode("delay").getChildNode("near_threshold").getText(0));
			sscanf(temp_var, "%lf", &(SENSE_AMP_D));
			strcpy(temp_var,senseAmp_node.getChildNode("energy").getChildNode("near_threshold").getText(0));
			sscanf(temp_var, "%lf", &(SENSE_AMP_P));
		} else {
			strcpy(temp_var,senseAmp_node.getChildNode("delay").getChildNode("super_threshold").getText(0));
			sscanf(temp_var, "%lf", &(SENSE_AMP_D));
			strcpy(temp_var,senseAmp_node.getChildNode("energy").getChildNode("super_threshold").getText(0));
			sscanf(temp_var, "%lf", &(SENSE_AMP_P));
		}

		char temperature[10];
		sprintf(temperature,"%d",g_ip->temp);
		NMOS_ONcurrents_node = root_node.getChildNode("currents").getChildNode("ON_current").getChildNode("NMOS");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,NMOS_ONcurrents_node.getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_on_n));
		} else {
			strcpy(temp_var,NMOS_ONcurrents_node.getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_on_n));
		}

		PMOS_ONcurrents_node = root_node.getChildNode("currents").getChildNode("ON_current").getChildNode("PMOS");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,PMOS_ONcurrents_node.getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_on_p));
		} else {
			strcpy(temp_var,PMOS_ONcurrents_node.getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_on_p));
		}

		NMOS_OFFcurrents_node = root_node.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,NMOS_OFFcurrents_node.getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_off_n));
		} else {
			strcpy(temp_var,NMOS_OFFcurrents_node.getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_off_n));
		}

		PMOS_OFFcurrents_node = root_node.getChildNode("currents").getChildNode("OFF_current").getChildNode("PMOS");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,PMOS_OFFcurrents_node.getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_off_p));
		} else {
			strcpy(temp_var,PMOS_OFFcurrents_node.getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_off_p));
		}
		//---------- Majid - END ------------

		/***** Alireza - BEGIN *****/
		if (g_ip->is_finfet) {
			vbit_sense_min = 0.04;
			g_tp.sram_cell.P_fin   += curr_alpha * p_fin;
			g_tp.sram_cell.H_fin   += curr_alpha * h_fin;
			g_tp.sram_cell.T_si    += curr_alpha * t_si;
            g_tp.sram_cell.W_fin   += curr_alpha * w_fin;
			// FinFET-based SRAM cell properties:
			double sram_cell_height, sram_cell_width;
			sram_cell_height = g_ip->sram_cell_design.calc_height(lambda_um);
			sram_cell_width = g_ip->sram_cell_design.calc_width(lambda_um, p_fin, t_si);
			int n[5];
			g_ip->sram_cell_design.getNfins(n);
			curr_Wmemcella_sram      = n[0] * (2 * h_fin + w_fin);
			curr_Wmemcellpmos_sram   = n[1] * (2 * h_fin + w_fin);
			curr_Wmemcellnmos_sram   = n[2] * (2 * h_fin + w_fin);
			curr_Wmemcellrdiso_sram  = n[3] * (2 * h_fin + w_fin);
			curr_Wmemcellrda_sram    = n[4] * (2 * h_fin + w_fin);
			curr_area_cell_sram      = sram_cell_height * sram_cell_width;
			curr_asp_ratio_cell_sram = sram_cell_height / sram_cell_width;
		} else {
			vbit_sense_min = 0.08;
			// CMOS-based SRAM cell properties:
			if ( g_ip->sram_cell_design.getType() == std_6T ) {
				curr_Wmemcella_sram      = 1.31 * g_ip->F_sz_um;
				curr_Wmemcellpmos_sram   = 1.23 * g_ip->F_sz_um;
				curr_Wmemcellnmos_sram   = 2.08 * g_ip->F_sz_um;
				curr_area_cell_sram      = 146 * g_ip->F_sz_um * g_ip->F_sz_um;
				curr_asp_ratio_cell_sram = 1.46;
			} else if ( g_ip->sram_cell_design.getType() == std_8T ) {
				// Source: Chang et al., "Stable SRAM cell design for the 32 nm node and beyond," VLSI Symposia 2005.
				curr_Wmemcella_sram      = 1.0 * g_ip->F_sz_um;
				curr_Wmemcellpmos_sram   = 1.0 * g_ip->F_sz_um;
				curr_Wmemcellnmos_sram   = 1.0 * g_ip->F_sz_um;
				curr_Wmemcellrda_sram    = 1.0 * g_ip->F_sz_um;
				curr_Wmemcellrdiso_sram  = 3.5 * g_ip->F_sz_um;
				curr_area_cell_sram      = 195 * g_ip->F_sz_um * g_ip->F_sz_um;
				curr_asp_ratio_cell_sram = 0.36;
			} else {
				cout << "ERROR: Invalid SRAM cell type in technology.cc!\n";
				exit(0);
			}
		}

		g_tp.Vbit_sense_min = vbit_sense_min;

		delta_L = (g_ip->is_finfet) ? (2*0.8*Xj) : (0.8*Xj);
		c_gate = Lphy * c_ox;
        c_g_ideal = c_gate;
		Lelec = Lphy - delta_L;
		if ( Lelec <=0 ) {
			cout << "ERROR: Lelec (ram_cell) is not a positive value! Please check the Lphy or the Xj value.\n";
			exit(0);
		}
		I_on_n_to_I_on_p_ratio = I_on_n / I_on_p;
        n_to_p_eff_curr_drv_ratio = I_on_n_to_I_on_p_ratio;
		Rnchannelon = vdd_cell / I_on_n;
		Rpchannelon = vdd_cell / I_on_p;
		g_tp.sram_cell.Vdd       += curr_alpha * vdd_cell;
		g_tp.sram_cell.l_phy     += curr_alpha * Lphy;
		g_tp.sram_cell.l_elec    += curr_alpha * Lelec;
		g_tp.sram_cell.t_ox      += curr_alpha * t_ox;
		g_tp.sram_cell.Vth       += curr_alpha * v_th;
		g_tp.sram_cell.C_g_ideal += curr_alpha * c_g_ideal;
		g_tp.sram_cell.C_fringe  += curr_alpha * c_fringe;
		g_tp.sram_cell.C_junc    += curr_alpha * c_junc;
		g_tp.sram_cell.C_junc_sidewall = c_junc_sidewall;
		g_tp.sram_cell.I_on_n    += curr_alpha * I_on_n;
        g_tp.sram_cell.I_on_p    += curr_alpha * I_on_p;
		g_tp.sram_cell.I_off_n   += curr_alpha * I_off_n;
		g_tp.sram_cell.I_off_p   += curr_alpha * I_off_p;
		g_tp.sram_cell.R_nch_on  += curr_alpha * Rnchannelon;
		g_tp.sram_cell.R_pch_on  += curr_alpha * Rpchannelon;
		g_tp.sram_cell.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
		g_tp.cam_cell.Vdd       += curr_alpha * vdd_cell;
		g_tp.cam_cell.l_phy     += curr_alpha * Lphy;
		g_tp.cam_cell.l_elec    += curr_alpha * Lelec;
		g_tp.cam_cell.t_ox      += curr_alpha * t_ox;
		g_tp.cam_cell.Vth       += curr_alpha * v_th;
		g_tp.cam_cell.C_g_ideal += curr_alpha * c_g_ideal;
		g_tp.cam_cell.C_fringe  += curr_alpha * c_fringe;
		g_tp.cam_cell.C_junc    += curr_alpha * c_junc;
		g_tp.cam_cell.C_junc_sidewall = c_junc_sidewall;
		g_tp.cam_cell.I_on_n    += curr_alpha * I_on_n;
        g_tp.cam_cell.I_on_p    += curr_alpha * I_on_p;
		g_tp.cam_cell.I_off_n   += curr_alpha * I_off_n;
		g_tp.cam_cell.I_off_p   += curr_alpha * I_off_p;
		g_tp.cam_cell.R_nch_on  += curr_alpha * Rnchannelon;
		g_tp.cam_cell.R_pch_on  += curr_alpha * Rpchannelon;
		g_tp.cam_cell.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
        curr_Wmemcella_cam = curr_Wmemcella_sram;
        curr_Wmemcellpmos_cam = curr_Wmemcellpmos_sram;
        curr_Wmemcellnmos_cam = curr_Wmemcellnmos_sram;
        curr_area_cell_cam = 2 * curr_area_cell_sram;
        curr_asp_ratio_cell_cam = 2 * curr_asp_ratio_cell_sram;

		/****** Alireza - END ******/
		//-------------------- cell parameters end ----------------------------


		//-------------------- peripheral parameters begin --------------------
		//---------- Majid - BEGIN ----------
		if ( is_tag ) {
			root_node = XMLNode::openFileHelper(g_ip->tag_array_peri_tech_file,"device_definition");
		} else {
			root_node = XMLNode::openFileHelper(g_ip->data_array_peri_tech_file,"device_definition");
		}

		geometry_node = root_node.getChildNode("geometries");
		strcpy(temp_var,geometry_node.getChildNode("Lphy").getText(0));
		sscanf(temp_var, "%lf", &(Lphy));
		strcpy(temp_var,geometry_node.getChildNode("Xj").getText(0));
		sscanf(temp_var, "%lf", &(Xj));
		strcpy(temp_var,geometry_node.getChildNode("t_ox").getText(0));
		sscanf(temp_var, "%lf", &(t_ox));
		if ( g_ip->is_finfet ) {
			strcpy(temp_var,geometry_node.getChildNode("FinFET").getChildNode("t_si").getText(0));
			sscanf(temp_var, "%lf", &(t_si));
			strcpy(temp_var,geometry_node.getChildNode("FinFET").getChildNode("h_fin").getText(0));
			sscanf(temp_var, "%lf", &(h_fin));
			if ( !geometry_node.getChildNode("FinFET").getChildNode("p_fin").isEmpty() ) {
				strcpy(temp_var,geometry_node.getChildNode("FinFET").getChildNode("p_fin").getText(0));
				sscanf(temp_var, "%lf", &(p_fin));
			} else {
				p_fin = (2 * lambda_um) + t_si;
			}
		}

		w_fin = g_ip->is_finfet ? t_si : 0;
		voltages_node = root_node.getChildNode("voltages");
		strcpy(temp_var,voltages_node.getChildNode("v_th").getText(0));
		sscanf(temp_var, "%lf", &(v_th));
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,voltages_node.getChildNode("vdd").getChildNode("near_threshold").getText(0));
			sscanf(temp_var, "%lf", &(vdd_peri));
			strcpy(temp_var,voltages_node.getChildNode("Vdsat").getChildNode("near_threshold").getText(0));
			sscanf(temp_var, "%lf", &(Vdsat));
		} else {
			strcpy(temp_var,voltages_node.getChildNode("vdd").getChildNode("super_threshold").getText(0));
			sscanf(temp_var, "%lf", &(vdd_peri));
			strcpy(temp_var,voltages_node.getChildNode("Vdsat").getChildNode("super_threshold").getText(0));
			sscanf(temp_var, "%lf", &(Vdsat));
		}

		cap_node = root_node.getChildNode("capacitances");
		strcpy(temp_var,cap_node.getChildNode("c_ox").getText(0));
		sscanf(temp_var, "%lf", &(c_ox));
		strcpy(temp_var,cap_node.getChildNode("c_junc_sidewall").getText(0));
		sscanf(temp_var, "%lf", &(c_junc_sidewall));
		strcpy(temp_var,cap_node.getChildNode("c_junc_sidewall_gate").getText(0));
		sscanf(temp_var, "%lf", &(c_junc_sidewall_gate));
		strcpy(temp_var,cap_node.getChildNode("c_junc").getText(0));
		sscanf(temp_var, "%lf", &(c_junc));
		strcpy(temp_var,cap_node.getChildNode("c_fringe").getText(0));
		sscanf(temp_var, "%lf", &(c_fringe));

		strcpy(temp_var,root_node.getChildNode("mobility_eff").getText(0));
		sscanf(temp_var, "%lf", &(mobility_eff));

		strcpy(temp_var,root_node.getChildNode("gmp_to_gmn_multiplier").getText(0));
		sscanf(temp_var, "%lf", &(gmp_to_gmn_multiplier));

		NMOS_ONcurrents_node = root_node.getChildNode("currents").getChildNode("ON_current").getChildNode("NMOS");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,NMOS_ONcurrents_node.getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_on_n));
		} else {
			strcpy(temp_var,NMOS_ONcurrents_node.getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_on_n));
		}

		PMOS_ONcurrents_node = root_node.getChildNode("currents").getChildNode("ON_current").getChildNode("PMOS");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,PMOS_ONcurrents_node.getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_on_p));
		} else {
			strcpy(temp_var,PMOS_ONcurrents_node.getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_on_p));
		}

		NMOS_OFFcurrents_node = root_node.getChildNode("currents").getChildNode("OFF_current").getChildNode("NMOS");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,NMOS_OFFcurrents_node.getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_off_n));
		} else {
			strcpy(temp_var,NMOS_OFFcurrents_node.getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_off_n));
		}

		PMOS_OFFcurrents_node = root_node.getChildNode("currents").getChildNode("OFF_current").getChildNode("PMOS");
		if ( g_ip->is_near_threshold ) {
			strcpy(temp_var,PMOS_OFFcurrents_node.getChildNode("near_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_off_p));
		} else {
			strcpy(temp_var,PMOS_OFFcurrents_node.getChildNode("super_threshold").getChildNodeWithAttribute("temp","val",temperature).getText(0));
			sscanf(temp_var, "%lf", &(I_off_p));
		}
		//---------- Majid - END ------------

		/***** Alireza - BEGIN *****/
		if (g_ip->is_finfet) {
			g_tp.peri_global.P_fin += curr_alpha * p_fin;
			g_tp.peri_global.H_fin += curr_alpha * h_fin;
			g_tp.peri_global.T_si  += curr_alpha * t_si;
            g_tp.peri_global.W_fin += curr_alpha * w_fin;
		}

		delta_L = (g_ip->is_finfet) ? (2*0.8*Xj) : (0.8*Xj);
		c_gate = Lphy * c_ox;
        c_g_ideal = c_gate;
		Lelec = Lphy - delta_L;
		if ( Lelec <= 0 ) {
			cout << "ERROR: Lelec (peri_global) is not a positive value! Please check the Lphy or the Xj value.\n";
			exit(0);
		}
		I_on_n_to_I_on_p_ratio = I_on_n / I_on_p;
        n_to_p_eff_curr_drv_ratio = I_on_n_to_I_on_p_ratio;
		Rnchannelon = vdd_peri / I_on_n;
		Rpchannelon = vdd_peri / I_on_p;
		g_tp.peri_global.Vdd       += curr_alpha * vdd_peri;
		g_tp.peri_global.t_ox      += curr_alpha * t_ox;
		g_tp.peri_global.Vth       += curr_alpha * v_th;
		g_tp.peri_global.C_ox      += curr_alpha * c_ox;
		g_tp.peri_global.C_g_ideal += curr_alpha * c_g_ideal;
		g_tp.peri_global.C_fringe  += curr_alpha * c_fringe;
		g_tp.peri_global.C_junc    += curr_alpha * c_junc;
		g_tp.peri_global.C_junc_sidewall = c_junc_sidewall;
		g_tp.peri_global.l_phy     += curr_alpha * Lphy;
		g_tp.peri_global.l_elec    += curr_alpha * Lelec;
		g_tp.peri_global.I_on_n    += curr_alpha * I_on_n;
		g_tp.peri_global.I_off_n   += curr_alpha * I_off_n;
		g_tp.peri_global.I_off_p   += curr_alpha * I_off_p;
		g_tp.peri_global.R_nch_on  += curr_alpha * Rnchannelon;
		g_tp.peri_global.R_pch_on  += curr_alpha * Rpchannelon;
		g_tp.peri_global.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
		gmp_to_gmn_multiplier_periph_global += curr_alpha * gmp_to_gmn_multiplier;
		/****** Alireza - END ******/
		//-------------------- peripheral parameters end ----------------------

        // FN McPAT scaling constants have no node-specific XML data.
        curr_logic_scaling_co_eff = 0.7*0.7*0.7*0.7*0.7;
        curr_core_tx_density = 1.25/0.7/0.7/0.7;
        curr_sckt_co_eff = 1.1296;
        curr_chip_layout_overhead = 1.2;
        curr_macro_layout_overhead = 1.1;
        } else {
          cerr << "ERROR: no device data for tech/transistor." << endl;
          exit(1);
        }
			// Divya begin. To update SRAM cell Ioff when dvs is true
//			if(g_ip->is_dvs && g_ip->is_finfet) {
			if((!g_ip->dvs_voltage.empty()) && g_ip->is_finfet) {
                if (g_ip->use_device_xml) {
                  g_ip->load_sram_cell_xml();
                } else {
			//Considering for 6T SRAM cell only, not for 8T sram cell
				Ioffs[0] = g_tp.sram_cell.I_off_n;	//acc
				Ioffs[1] = g_tp.sram_cell.I_off_p; //pup
				Ioffs[2] = g_tp.sram_cell.I_off_n; //pdn

				g_ip->sram_cell_design.setTransistorParams(g_ip->Nfins, g_ip->Lphys, Ioffs);
                }
//				cout << "Io : " << Ioffs[0] << ", I1 : " << Ioffs[1] << ", I2 : " << Ioffs[2] << endl;
			}

// Divya Modifying end --

		// TO DO: Update This!
		//-------------------- dram parameters begin --------------------------
		c_g_ideal = Lphy_dram * c_ox_dram;
		Lelec = Lphy_dram - delta_L;

		n_to_p_eff_curr_drv_ratio = I_on_n_dram / I_on_p_dram;
		Rnchannelon = nmos_effective_resistance_multiplier*curr_vdd_dram_cell / I_on_n_dram;
		Rpchannelon = n_to_p_eff_curr_drv_ratio*Rnchannelon;
		g_tp.dram_cell_Vdd      += curr_alpha * curr_vdd_dram_cell;	//ok
		g_tp.dram_acc.Vth       += curr_alpha * curr_v_th_dram_access_transistor;	//ok
		g_tp.dram_acc.l_phy     += curr_alpha * Lphy_dram;	//ok
		g_tp.dram_acc.l_elec    += curr_alpha * Lelec;
		g_tp.dram_acc.C_g_ideal += curr_alpha * c_g_ideal;	//c_g_ideal
		g_tp.dram_acc.C_fringe  += curr_alpha * c_fringe_dram;
		g_tp.dram_acc.C_junc    += curr_alpha * c_junc_dram;
		g_tp.dram_acc.C_junc_sidewall = (g_ip->is_finfet) ? c_junc_sidewall:  0.25e-15; //F/um
		g_tp.dram_cell_I_on     += curr_alpha * curr_I_on_dram_cell;
		g_tp.dram_cell_I_off_worst_case_len_temp += curr_alpha * curr_I_off_dram_cell_worst_case_length_temp;
		g_tp.dram_acc.I_on_n    += curr_alpha * I_on_n_dram;
		g_tp.dram_cell_C        += curr_alpha * curr_c_dram_cell;
		g_tp.vpp                += curr_alpha * curr_vpp;
		g_tp.dram_wl.l_phy      += curr_alpha * Lphy_dram;
		g_tp.dram_wl.l_elec     += curr_alpha * Lelec;
		g_tp.dram_wl.C_g_ideal  += curr_alpha * c_g_ideal;
		g_tp.dram_wl.C_fringe   += curr_alpha * c_fringe_dram;
		g_tp.dram_wl.C_junc     += curr_alpha * c_junc_dram;
		g_tp.dram_wl.C_junc_sidewall =  (g_ip->is_finfet) ? c_junc_sidewall:  0.25e-15; //F/um;
		g_tp.dram_wl.I_on_n     += curr_alpha * I_on_n_dram;
		g_tp.dram_wl.I_off_n    += curr_alpha * I_off_n_dram;
		g_tp.dram_wl.I_off_p    += curr_alpha * I_off_n_dram;
		g_tp.dram_wl.R_nch_on   += curr_alpha * Rnchannelon;
		g_tp.dram_wl.R_pch_on   += curr_alpha * Rpchannelon;
		g_tp.dram_wl.n_to_p_eff_curr_drv_ratio += curr_alpha * n_to_p_eff_curr_drv_ratio;
		//-------------------- dram parameters end ----------------------------

		g_tp.dram.cell_a_w    += curr_alpha * curr_Wmemcella_dram;
		g_tp.dram.cell_pmos_w += curr_alpha * curr_Wmemcellpmos_dram;
		g_tp.dram.cell_nmos_w += curr_alpha * curr_Wmemcellnmos_dram;
		area_cell_dram        += curr_alpha * curr_area_cell_dram;
		asp_ratio_cell_dram   += curr_alpha * curr_asp_ratio_cell_dram;
		
		g_tp.sram.cell_a_w      += curr_alpha * curr_Wmemcella_sram;
		g_tp.sram.cell_pmos_w   += curr_alpha * curr_Wmemcellpmos_sram;
		g_tp.sram.cell_nmos_w   += curr_alpha * curr_Wmemcellnmos_sram;
		g_tp.sram.cell_rd_a_w   += curr_alpha * curr_Wmemcellrda_sram; // Alireza: for 8T SRAM cell
		g_tp.sram.cell_rd_iso_w += curr_alpha * curr_Wmemcellrdiso_sram; // Alireza: for 8T SRAM cell
		area_cell_sram          += curr_alpha * curr_area_cell_sram;
		asp_ratio_cell_sram     += curr_alpha * curr_asp_ratio_cell_sram;
		
	//			cout << "sram : curr_Wmemcella_sram : " << curr_Wmemcella_sram << ", curr_Wmemcellpmos_sram : " << curr_Wmemcellpmos_sram  << ", curr_Wmemcellnmos_sram : " << curr_Wmemcellnmos_sram <<
	//			", curr_area_cell_sram : " << curr_area_cell_sram << ", curr_asp_ratio_cell_sram : " << curr_asp_ratio_cell_sram << ", curr_alpha : " << curr_alpha << endl;
	    g_tp.cam.cell_a_w    += curr_alpha * curr_Wmemcella_cam;//sheng
	    g_tp.cam.cell_pmos_w += curr_alpha * curr_Wmemcellpmos_cam;
	    g_tp.cam.cell_nmos_w += curr_alpha * curr_Wmemcellnmos_cam;
	    area_cell_cam += curr_alpha * curr_area_cell_cam;
	    asp_ratio_cell_cam += curr_alpha * curr_asp_ratio_cell_cam;

		//Sense amplifier latch Gm calculation
		mobility_eff_periph_global += curr_alpha * mobility_eff; 
		Vdsat_periph_global        += curr_alpha * Vdsat;

	    //Empirical undifferetiated core/FU coefficient
	    g_tp.scaling_factor.logic_scaling_co_eff += curr_alpha * curr_logic_scaling_co_eff;
	    g_tp.scaling_factor.core_tx_density += curr_alpha * curr_core_tx_density;
	    g_tp.chip_layout_overhead  += curr_alpha * curr_chip_layout_overhead;
	    g_tp.macro_layout_overhead += curr_alpha * curr_macro_layout_overhead;
	    g_tp.sckt_co_eff           += curr_alpha * curr_sckt_co_eff;

//	    cout << "tech: " << tech << ", scaling: " << g_tp.scaling_factor.logic_scaling_co_eff << endl;
	}	//end of iter loop
	
	// TO DO: Update transistor sizes for FinFETs
	// Alireza: for CMOS we have "N * g_ip->F_sz_um", but this should be changed for FinFETs
	//Currently we are not modelling the resistance/capacitance of poly anywhere.
	g_tp.w_comp_inv_p1 = 12.5 * g_ip->F_sz_um;//this was 10 micron for the 0.8 micron process
	g_tp.w_comp_inv_n1 =  7.5 * g_ip->F_sz_um;//this was  6 micron for the 0.8 micron process
	g_tp.w_comp_inv_p2 =   25 * g_ip->F_sz_um;//this was 20 micron for the 0.8 micron process
	g_tp.w_comp_inv_n2 =   15 * g_ip->F_sz_um;//this was 12 micron for the 0.8 micron process
	g_tp.w_comp_inv_p3 =   50 * g_ip->F_sz_um;//this was 40 micron for the 0.8 micron process
	g_tp.w_comp_inv_n3 =   30 * g_ip->F_sz_um;//this was 24 micron for the 0.8 micron process
	g_tp.w_eval_inv_p  =  100 * g_ip->F_sz_um;//this was 80 micron for the 0.8 micron process
	g_tp.w_eval_inv_n  =   50 * g_ip->F_sz_um;//this was 40 micron for the 0.8 micron process
	g_tp.w_comp_n      = 12.5 * g_ip->F_sz_um;//this was 10 micron for the 0.8 micron process
	g_tp.w_comp_p      = 37.5 * g_ip->F_sz_um;//this was 30 micron for the 0.8 micron process

	g_tp.MIN_GAP_BET_P_AND_N_DIFFS = 5 * g_ip->F_sz_um;
	g_tp.MIN_GAP_BET_SAME_TYPE_DIFFS = 1.5 * g_ip->F_sz_um;
	g_tp.HPOWERRAIL = 2 * g_ip->F_sz_um;
	g_tp.cell_h_def = 50 * g_ip->F_sz_um; 
	g_tp.w_poly_contact = g_ip->F_sz_um;
	g_tp.spacing_poly_to_contact = g_ip->F_sz_um;
	g_tp.spacing_poly_to_poly = 1.5 * g_ip->F_sz_um;
	g_tp.ram_wl_stitching_overhead_ = 7.5 * g_ip->F_sz_um;
	
//Divya changes begin
	if ( g_ip->is_finfet) {	//  && g_ip->F_sz_um == 0.014 ) {
		g_tp.min_w_nmos_ = 2 * g_tp.peri_global.H_fin + g_tp.peri_global.W_fin; //g_tp.peri_global.W_fin;
		// transistor sizing of the finfet-based sense amplifier
		g_tp.w_iso       = 1 * (2 * h_fin + w_fin); //w_fin; // 1 fin
		g_tp.w_sense_n   = 1 * (2 * h_fin + w_fin); //w_fin;; // 1 fin
		g_tp.w_sense_p   = 1 * (2 * h_fin + w_fin); //w_fin;; // 1 fin
		g_tp.w_sense_en  = 1 * (2 * h_fin + w_fin); //w_fin;; // 1 fin
		//g_tp.NAND2_LEAK_STACK_FACTOR =
	} //Divya changes end
	else {
		g_tp.min_w_nmos_ = 3 * g_ip->F_sz_um / 2;
		// transistor sizing of the cmos-based sense amplifier
		g_tp.w_iso       = 12.5 * g_ip->F_sz_um; // was 10 micron for the 0.8 micron process
		g_tp.w_sense_n   = 3.75 * g_ip->F_sz_um; // sense amplifier N-trans; was 3 micron for the 0.8 micron process
		g_tp.w_sense_p   = 7.5  * g_ip->F_sz_um; // sense amplifier P-trans; was 6 micron for the 0.8 micron process
		g_tp.w_sense_en  = 5    * g_ip->F_sz_um; // Sense enable transistor of the sense amplifier; was 4 micron for the 0.8 micron process
	}
	/****** Alireza - END ******/
	
	g_tp.max_w_nmos_ = 100  * g_ip->F_sz_um; 
	g_tp.w_nmos_b_mux  = 6 * g_tp.min_w_nmos_;
	g_tp.w_nmos_sa_mux = 6 * g_tp.min_w_nmos_;

	if (ram_cell_tech_type == comm_dram) {
		g_tp.max_w_nmos_dec = 8 * g_ip->F_sz_um;
		g_tp.h_dec          = 8;  // in the unit of memory cell height
	} else {
		g_tp.max_w_nmos_dec = g_tp.max_w_nmos_;
		g_tp.h_dec          = 4;  // in the unit of memory cell height
	}

	if ( g_ip->is_finfet) {	//  && g_ip->F_sz_um == 0.014) {
		g_tp.peri_global.C_overlap = 0;
		g_tp.sram_cell.C_overlap   = 0;
		g_tp.cam_cell.C_overlap    = 0;
		g_tp.dram_acc.C_overlap    = 0;
		g_tp.dram_wl.C_overlap 	   = 0;
	} else {
	  g_tp.peri_global.C_overlap = 0.2 * g_tp.peri_global.C_g_ideal;
	  g_tp.sram_cell.C_overlap   = 0.2 * g_tp.sram_cell.C_g_ideal;
	  g_tp.cam_cell.C_overlap    = 0.2 * g_tp.cam_cell.C_g_ideal;
	  g_tp.dram_acc.C_overlap 	 = 0.2 * g_tp.dram_acc.C_g_ideal;
	  g_tp.dram_wl.C_overlap 	 = 0.2 * g_tp.dram_wl.C_g_ideal;
	}

	g_tp.dram_acc.R_nch_on = g_tp.dram_cell_Vdd / g_tp.dram_acc.I_on_n;
	//g_tp.dram_acc.R_pch_on = g_tp.dram_cell_Vdd / g_tp.dram_acc.I_on_p;

	double gmn_sense_amp_latch = (mobility_eff_periph_global / 2) * g_tp.peri_global.C_ox * (g_tp.w_sense_n / g_tp.peri_global.l_elec) * Vdsat_periph_global;
	double gmp_sense_amp_latch = gmp_to_gmn_multiplier_periph_global * gmn_sense_amp_latch;

	if(g_ip->is_finfet)
		g_tp.gm_sense_amp_latch = gmn_sense_amp_latch + gmp_sense_amp_latch;
	else
		g_tp.gm_sense_amp_latch = gmn_sense_amp_latch + gmp_sense_amp_latch * pow((g_tp.peri_global.Vdd-g_tp.peri_global.Vth)/(1.0 - g_tp.peri_global.Vth),1.3)/(g_tp.peri_global.Vdd/1.0);

	g_tp.dram.b_w = sqrt(area_cell_dram / (asp_ratio_cell_dram));
	g_tp.dram.b_h = asp_ratio_cell_dram * g_tp.dram.b_w;
	g_tp.sram.b_w = sqrt(area_cell_sram / (asp_ratio_cell_sram));
	g_tp.sram.b_h = asp_ratio_cell_sram * g_tp.sram.b_w;
	g_tp.cam.b_w =  sqrt(area_cell_cam / (asp_ratio_cell_cam));//Sheng
	g_tp.cam.b_h = asp_ratio_cell_cam * g_tp.cam.b_w;

	g_tp.dram.Vbitpre = g_tp.dram_cell_Vdd;
	g_tp.sram.Vbitpre = g_tp.sram_cell.Vdd;
    g_tp.cam.Vbitpre = g_tp.cam_cell.Vdd;//vdd[ram_cell_tech_type];//Sheng
	pmos_to_nmos_sizing_r = pmos_to_nmos_sz_ratio();
	g_tp.w_pmos_bl_precharge = 6 * pmos_to_nmos_sizing_r * g_tp.min_w_nmos_;
	g_tp.w_pmos_bl_eq = pmos_to_nmos_sizing_r * g_tp.min_w_nmos_;

	//-------------------- interconnect (wire) parameters begin --------------------------
    double wire_pitch       [NUMBER_INTERCONNECT_PROJECTION_TYPES][NUMBER_WIRE_TYPES],
           wire_r_per_micron[NUMBER_INTERCONNECT_PROJECTION_TYPES][NUMBER_WIRE_TYPES],
           wire_c_per_micron[NUMBER_INTERCONNECT_PROJECTION_TYPES][NUMBER_WIRE_TYPES],
    horiz_dielectric_constant[NUMBER_INTERCONNECT_PROJECTION_TYPES][NUMBER_WIRE_TYPES],
    vert_dielectric_constant[NUMBER_INTERCONNECT_PROJECTION_TYPES][NUMBER_WIRE_TYPES],
    aspect_ratio[NUMBER_INTERCONNECT_PROJECTION_TYPES][NUMBER_WIRE_TYPES],
    miller_value[NUMBER_INTERCONNECT_PROJECTION_TYPES][NUMBER_WIRE_TYPES],
    ild_thickness[NUMBER_INTERCONNECT_PROJECTION_TYPES][NUMBER_WIRE_TYPES];

    if ( wire_technology == 90 ) {        // 90nm CMOS
		tech_lo = 90; tech_hi = 90;
	} else if ( wire_technology == 65 ) { // 65nm CMOS
		tech_lo = 65; tech_hi = 65;
	} else if ( wire_technology == 45 ) { // 45nm CMOS
		tech_lo = 45; tech_hi = 45;
	} else if ( wire_technology == 32 ) { // 32nm CMOS
		tech_lo = 32; tech_hi = 32;
	} else if ( wire_technology == 22 ) { // 22nm CMOS
		tech_lo = 22; tech_hi = 22;
	} else if ( wire_technology == 16 ) { // 16nm CMOS
		tech_lo = 16; tech_hi = 16;
	} else if ( wire_technology == 14 ) { // 14nm CMOS
		tech_lo = 14; tech_hi = 14;
	} else if ( wire_technology == 7 ) {  // 7nm FinFET
		tech_lo = 7; tech_hi = 7;
	} else if ( wire_technology == 5 ) {  // 5nm FinFET
		tech_lo = 5; tech_hi = 5;
	} else if ( wire_technology < 90 && wire_technology > 65 ) { // 89nm -- 66nm
		tech_lo = 90; tech_hi = 65;
	} else if ( wire_technology < 65 && wire_technology > 45 ) { // 64nm -- 46nm
		tech_lo = 65; tech_hi = 45;
	} else if ( wire_technology < 45 && wire_technology > 32 ) { // 44nm -- 33nm
		tech_lo = 45; tech_hi = 32;
	} else if ( wire_technology < 32 && wire_technology > 22 ) { // 31nm -- 23nm
		tech_lo = 32; tech_hi = 22;
	} else if ( wire_technology < 22 && wire_technology > 16 ) { // 21nm -- 17nm
		tech_lo = 22; tech_hi = 16;
	} else if ( wire_technology < 16 && wire_technology > 14 ) { // 15nm
		tech_lo = 16; tech_hi = 14;
	} else {
		cout << "ERROR: Invalid technology node!" << endl;
		exit(0);
	}

    for (iter=0; iter<=1; ++iter)
    {
      // linear interpolation
      if (iter == 0) {
        tech = tech_lo;
        if (tech_lo == tech_hi) {
          curr_alpha = 1;
        } else {
          curr_alpha = (wire_technology - tech_hi)/(tech_lo - tech_hi);
        }
      } else {
        tech = tech_hi;
        if (tech_lo == tech_hi) {
          break;  
        } else {
          curr_alpha = (tech_lo - wire_technology)/(tech_lo - tech_hi);
        }
      }
//      cout << "interconnects tech: " << tech << ", asap7: " << g_ip->is_asap7 << endl;

      if (tech == 90) {
          //Aggressive projections
          wire_pitch[0][0] = 2.5 * g_ip->F_sz_um;//micron
          aspect_ratio[0][0] = 2.4;
          wire_width = wire_pitch[0][0] / 2; //micron
          wire_thickness = aspect_ratio[0][0] * wire_width;//micron
          wire_spacing = wire_pitch[0][0] - wire_width;//micron
          barrier_thickness = 0.01;//micron
          dishing_thickness = 0;//micron
          alpha_scatter = 1;
          wire_r_per_micron[0][0] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);//ohm/micron
          ild_thickness[0][0] = 0.48;//micron
          miller_value[0][0] = 1.5;
          horiz_dielectric_constant[0][0] = 2.709;
          vert_dielectric_constant[0][0] = 3.9;
          fringe_cap = 0.115e-15; //F/micron
          wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][0], miller_value[0][0], horiz_dielectric_constant[0][0],
              vert_dielectric_constant[0][0],
              fringe_cap);//F/micron.

          wire_pitch[0][1] = 4 * g_ip->F_sz_um;
          wire_width = wire_pitch[0][1] / 2;
          aspect_ratio[0][1] = 2.4;
          wire_thickness = aspect_ratio[0][1] * wire_width;
          wire_spacing = wire_pitch[0][1] - wire_width;
          wire_r_per_micron[0][1] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][1] = 0.48;//micron
          miller_value[0][1] = 1.5;
          horiz_dielectric_constant[0][1] = 2.709;
          vert_dielectric_constant[0][1] = 3.9;
          wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1],
              vert_dielectric_constant[0][1],
              fringe_cap);

          wire_pitch[0][2] = 8 * g_ip->F_sz_um;
          aspect_ratio[0][2] = 2.7;
          wire_width = wire_pitch[0][2] / 2;
          wire_thickness = aspect_ratio[0][2] * wire_width;
          wire_spacing = wire_pitch[0][2] - wire_width;
          wire_r_per_micron[0][2] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][2] = 0.96;
          miller_value[0][2] = 1.5;
          horiz_dielectric_constant[0][2] = 2.709;
          vert_dielectric_constant[0][2] = 3.9;
          wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2], vert_dielectric_constant[0][2],
              fringe_cap);

          //Conservative projections
          wire_pitch[1][0] = 2.5 * g_ip->F_sz_um;
          aspect_ratio[1][0]  = 2.0;
          wire_width = wire_pitch[1][0] / 2;
          wire_thickness = aspect_ratio[1][0] * wire_width;
          wire_spacing = wire_pitch[1][0] - wire_width;
          barrier_thickness = 0.008;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][0]  = 0.48;
          miller_value[1][0]  = 1.5;
          horiz_dielectric_constant[1][0]  = 3.038;
          vert_dielectric_constant[1][0]  = 3.9;
          fringe_cap = 0.115e-15;
          wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][0], miller_value[1][0], horiz_dielectric_constant[1][0],
              vert_dielectric_constant[1][0],
              fringe_cap);

          wire_pitch[1][1] = 4 * g_ip->F_sz_um;
          wire_width = wire_pitch[1][1] / 2;
          aspect_ratio[1][1] = 2.0;
          wire_thickness = aspect_ratio[1][1] * wire_width;
          wire_spacing = wire_pitch[1][1] - wire_width;
          wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][1]  = 0.48;
          miller_value[1][1]  = 1.5;
          horiz_dielectric_constant[1][1]  = 3.038;
          vert_dielectric_constant[1][1]  = 3.9;
          wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1],
              vert_dielectric_constant[1][1],
              fringe_cap);

          wire_pitch[1][2] = 8 * g_ip->F_sz_um;
          aspect_ratio[1][2]  = 2.2;
          wire_width = wire_pitch[1][2] / 2;
          wire_thickness = aspect_ratio[1][2] * wire_width;
          wire_spacing = wire_pitch[1][2] - wire_width;
          dishing_thickness = 0.1 *  wire_thickness;
          wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][2]  = 1.1;
          miller_value[1][2]  = 1.5;
          horiz_dielectric_constant[1][2]  = 3.038;
          vert_dielectric_constant[1][2]  = 3.9;
          wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][2] , miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
              fringe_cap);
          //Nominal projections for commodity DRAM wordline/bitline
          wire_pitch[1][3] = 2 * 0.09;
          wire_c_per_micron[1][3] = 60e-15 / (256 * 2 * 0.09);
          wire_r_per_micron[1][3] = 12 / 0.09;
        }
        else if (tech == 65)
        {
          //Aggressive projections
          wire_pitch[0][0] = 2.5 * g_ip->F_sz_um;
          aspect_ratio[0][0]  = 2.7;
          wire_width = wire_pitch[0][0] / 2;
          wire_thickness = aspect_ratio[0][0]  * wire_width;
          wire_spacing = wire_pitch[0][0] - wire_width;
          barrier_thickness = 0;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[0][0] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][0]  = 0.405;
          miller_value[0][0]   = 1.5;
          horiz_dielectric_constant[0][0]  = 2.303;
          vert_dielectric_constant[0][0]   = 3.9;
          fringe_cap = 0.115e-15;
          wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][0] , miller_value[0][0] , horiz_dielectric_constant[0][0] , vert_dielectric_constant[0][0] ,
              fringe_cap);

          wire_pitch[0][1] = 4 * g_ip->F_sz_um;
          wire_width = wire_pitch[0][1] / 2;
          aspect_ratio[0][1]  = 2.7;
          wire_thickness = aspect_ratio[0][1]  * wire_width;
          wire_spacing = wire_pitch[0][1] - wire_width;
          wire_r_per_micron[0][1] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][1]  = 0.405;
          miller_value[0][1]   = 1.5;
          horiz_dielectric_constant[0][1]  = 2.303;
          vert_dielectric_constant[0][1]   = 3.9;
          wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1],
              vert_dielectric_constant[0][1],
              fringe_cap);

          wire_pitch[0][2] = 8 * g_ip->F_sz_um;
          aspect_ratio[0][2] = 2.8;
          wire_width = wire_pitch[0][2] / 2;
          wire_thickness = aspect_ratio[0][2] * wire_width;
          wire_spacing = wire_pitch[0][2] - wire_width;
          wire_r_per_micron[0][2] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][2] = 0.81;
          miller_value[0][2]   = 1.5;
          horiz_dielectric_constant[0][2]  = 2.303;
          vert_dielectric_constant[0][2]   = 3.9;
          wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2], vert_dielectric_constant[0][2],
              fringe_cap);

          //Conservative projections
          wire_pitch[1][0] = 2.5 * g_ip->F_sz_um;
          aspect_ratio[1][0] = 2.0;
          wire_width = wire_pitch[1][0] / 2;
          wire_thickness = aspect_ratio[1][0] * wire_width;
          wire_spacing = wire_pitch[1][0] - wire_width;
          barrier_thickness = 0.006;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][0] = 0.405;
          miller_value[1][0] = 1.5;
          horiz_dielectric_constant[1][0] = 2.734;
          vert_dielectric_constant[1][0] = 3.9;
          fringe_cap = 0.115e-15;
          wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][0], miller_value[1][0], horiz_dielectric_constant[1][0], vert_dielectric_constant[1][0],
              fringe_cap);

          wire_pitch[1][1] = 4 * g_ip->F_sz_um;
          wire_width = wire_pitch[1][1] / 2;
          aspect_ratio[1][1] = 2.0;
          wire_thickness = aspect_ratio[1][1] * wire_width;
          wire_spacing = wire_pitch[1][1] - wire_width;
          wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][1] = 0.405;
          miller_value[1][1] = 1.5;
          horiz_dielectric_constant[1][1] = 2.734;
          vert_dielectric_constant[1][1] = 3.9;
          wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1], vert_dielectric_constant[1][1],
              fringe_cap);

          wire_pitch[1][2] = 8 * g_ip->F_sz_um;
          aspect_ratio[1][2] = 2.2;
          wire_width = wire_pitch[1][2] / 2;
          wire_thickness = aspect_ratio[1][2] * wire_width;
          wire_spacing = wire_pitch[1][2] - wire_width;
          dishing_thickness = 0.1 *  wire_thickness;
          wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][2] = 0.77;
          miller_value[1][2] = 1.5;
          horiz_dielectric_constant[1][2] = 2.734;
          vert_dielectric_constant[1][2] = 3.9;
          wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][2], miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
              fringe_cap);
          //Nominal projections for commodity DRAM wordline/bitline
          wire_pitch[1][3] = 2 * 0.065;
          wire_c_per_micron[1][3] = 52.5e-15 / (256 * 2 * 0.065);
          wire_r_per_micron[1][3] = 12 / 0.065;
        }
      else if (tech == 45) {
          //Aggressive projections.
          wire_pitch[0][0] = 2.5 * g_ip->F_sz_um;
          aspect_ratio[0][0]  = 3.0;
          wire_width = wire_pitch[0][0] / 2;
          wire_thickness = aspect_ratio[0][0]  * wire_width;
          wire_spacing = wire_pitch[0][0] - wire_width;
          barrier_thickness = 0;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[0][0] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][0]  = 0.315;
          miller_value[0][0]  = 1.5;
          horiz_dielectric_constant[0][0]  = 1.958;
          vert_dielectric_constant[0][0]  = 3.9;
          fringe_cap = 0.115e-15;
          wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][0] , miller_value[0][0] , horiz_dielectric_constant[0][0] , vert_dielectric_constant[0][0] ,
              fringe_cap);

          wire_pitch[0][1] = 4 * g_ip->F_sz_um;
          wire_width = wire_pitch[0][1] / 2;
          aspect_ratio[0][1]  = 3.0;
          wire_thickness = aspect_ratio[0][1] * wire_width;
          wire_spacing = wire_pitch[0][1] - wire_width;
          wire_r_per_micron[0][1] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][1]  = 0.315;
          miller_value[0][1]  = 1.5;
          horiz_dielectric_constant[0][1]  = 1.958;
          vert_dielectric_constant[0][1]  = 3.9;
          wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1], vert_dielectric_constant[0][1],
              fringe_cap);

          wire_pitch[0][2] = 8 * g_ip->F_sz_um;
          aspect_ratio[0][2] = 3.0;
          wire_width = wire_pitch[0][2] / 2;
          wire_thickness = aspect_ratio[0][2] * wire_width;
          wire_spacing = wire_pitch[0][2] - wire_width;
          wire_r_per_micron[0][2] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][2] = 0.63;
          miller_value[0][2]  = 1.5;
          horiz_dielectric_constant[0][2]  = 1.958;
          vert_dielectric_constant[0][2]  = 3.9;
          wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2], vert_dielectric_constant[0][2],
              fringe_cap);
    /*
          cout << "wire_pitch[0][0]: " << wire_pitch[0][0]
    				<< ", wire_r_per_micron[0][0]: " << wire_r_per_micron[0][0]
    				<< ", wire_c_per_micron[0][0]: "  << wire_c_per_micron[0][0]
    			  << "wire_pitch[0][1]: " << wire_pitch[0][1]
    				<< ", wire_r_per_micron[0][1]: " << wire_r_per_micron[0][1]
    				<< ", wire_c_per_micron[0][1]: "  << wire_c_per_micron[0][1]
    				  << "wire_pitch[0][2]: " <<wire_pitch[0][2]
    				<< ", wire_r_per_micron[0][2]: " << wire_r_per_micron[0][2]
    				<< ", wire_c_per_micron[0][2]: "  << wire_c_per_micron[0][2]
    								<< endl;
    */
         //Conservative projections
          wire_pitch[1][0] = 2.5 * g_ip->F_sz_um;
          aspect_ratio[1][0] = 2.0;
          wire_width = wire_pitch[1][0] / 2;
          wire_thickness = aspect_ratio[1][0] * wire_width;
          wire_spacing = wire_pitch[1][0] - wire_width;
          barrier_thickness = 0.004;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][0] = 0.315;
          miller_value[1][0] = 1.5;
          horiz_dielectric_constant[1][0] = 2.46;
          vert_dielectric_constant[1][0] = 3.9;
          fringe_cap = 0.115e-15;
          wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][0], miller_value[1][0], horiz_dielectric_constant[1][0], vert_dielectric_constant[1][0],
              fringe_cap);

          wire_pitch[1][1] = 4 * g_ip->F_sz_um;
          wire_width = wire_pitch[1][1] / 2;
          aspect_ratio[1][1] = 2.0;
          wire_thickness = aspect_ratio[1][1] * wire_width;
          wire_spacing = wire_pitch[1][1] - wire_width;
          wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][1] = 0.315;
          miller_value[1][1] = 1.5;
          horiz_dielectric_constant[1][1] = 2.46;
          vert_dielectric_constant[1][1] = 3.9;
          fringe_cap = 0.115e-15;
          wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1], vert_dielectric_constant[1][1],
              fringe_cap);

          wire_pitch[1][2] = 8 * g_ip->F_sz_um;
          aspect_ratio[1][2] = 2.2;
          wire_width = wire_pitch[1][2] / 2;
          wire_thickness = aspect_ratio[1][2] * wire_width;
          wire_spacing = wire_pitch[1][2] - wire_width;
          dishing_thickness = 0.1 * wire_thickness;
          wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][2] = 0.55;
          miller_value[1][2] = 1.5;
          horiz_dielectric_constant[1][2] = 2.46;
          vert_dielectric_constant[1][2] = 3.9;
          wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][2], miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
              fringe_cap);
          //Nominal projections for commodity DRAM wordline/bitline
          wire_pitch[1][3] = 2 * 0.045;
          wire_c_per_micron[1][3] = 37.5e-15 / (256 * 2 * 0.045);
          wire_r_per_micron[1][3] = 12 / 0.045;
        }
      else if (tech == 32) {
        if ( !g_ip->is_itrs2012 ) { // wire data from Ron Ho's PhD Thesis, Stanford, 2003.
          //Aggressive projections.
            //Aggressive projections.
            wire_pitch[0][0] = 2.5 * g_ip->F_sz_um;
            aspect_ratio[0][0] = 3.0;
            wire_width = wire_pitch[0][0] / 2;
            wire_thickness = aspect_ratio[0][0] * wire_width;
            wire_spacing = wire_pitch[0][0] - wire_width;
            barrier_thickness = 0;
            dishing_thickness = 0;
            alpha_scatter = 1;
            wire_r_per_micron[0][0] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
                wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[0][0] = 0.21;
            miller_value[0][0] = 1.5;
            horiz_dielectric_constant[0][0] = 1.664;
            vert_dielectric_constant[0][0] = 3.9;
            fringe_cap = 0.115e-15;
            wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
                ild_thickness[0][0], miller_value[0][0], horiz_dielectric_constant[0][0], vert_dielectric_constant[0][0],
                fringe_cap);

            wire_pitch[0][1] = 4 * g_ip->F_sz_um;
            wire_width = wire_pitch[0][1] / 2;
            aspect_ratio[0][1] = 3.0;
            wire_thickness = aspect_ratio[0][1] * wire_width;
            wire_spacing = wire_pitch[0][1] - wire_width;
            wire_r_per_micron[0][1] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
                wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[0][1] = 0.21;
            miller_value[0][1] = 1.5;
            horiz_dielectric_constant[0][1] = 1.664;
            vert_dielectric_constant[0][1] = 3.9;
            wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
                ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1], vert_dielectric_constant[0][1],
                fringe_cap);

            wire_pitch[0][2] = 8 * g_ip->F_sz_um;
            aspect_ratio[0][2] = 3.0;
            wire_width = wire_pitch[0][2] / 2;
            wire_thickness = aspect_ratio[0][2] * wire_width;
            wire_spacing = wire_pitch[0][2] - wire_width;
            wire_r_per_micron[0][2] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
                wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[0][2] = 0.42;
            miller_value[0][2] = 1.5;
            horiz_dielectric_constant[0][2] = 1.664;
            vert_dielectric_constant[0][2] = 3.9;
            wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
                ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2], vert_dielectric_constant[0][2],
                fringe_cap);

            //Conservative projections
            wire_pitch[1][0] = 2.5 * g_ip->F_sz_um;
            aspect_ratio[1][0] = 2.0;
            wire_width = wire_pitch[1][0] / 2;
            wire_thickness = aspect_ratio[1][0] * wire_width;
            wire_spacing = wire_pitch[1][0] - wire_width;
            barrier_thickness = 0.003;
            dishing_thickness = 0;
            alpha_scatter = 1;
            wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
                wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[1][0] = 0.21;
            miller_value[1][0] = 1.5;
            horiz_dielectric_constant[1][0] = 2.214;
            vert_dielectric_constant[1][0] = 3.9;
            fringe_cap = 0.115e-15;
            wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
                ild_thickness[1][0], miller_value[1][0], horiz_dielectric_constant[1][0], vert_dielectric_constant[1][0],
                fringe_cap);

            wire_pitch[1][1] = 4 * g_ip->F_sz_um;
            aspect_ratio[1][1] = 2.0;
            wire_width = wire_pitch[1][1] / 2;
            wire_thickness = aspect_ratio[1][1] * wire_width;
            wire_spacing = wire_pitch[1][1] - wire_width;
            wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
                wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[1][1] = 0.21;
            miller_value[1][1] = 1.5;
            horiz_dielectric_constant[1][1] = 2.214;
            vert_dielectric_constant[1][1] = 3.9;
            wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
                ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1], vert_dielectric_constant[1][1],
                fringe_cap);

            wire_pitch[1][2] = 8 * g_ip->F_sz_um;
            aspect_ratio[1][2] = 2.2;
            wire_width = wire_pitch[1][2] / 2;
            wire_thickness = aspect_ratio[1][2] * wire_width;
            wire_spacing = wire_pitch[1][2] - wire_width;
            dishing_thickness = 0.1 *  wire_thickness;
            wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
                wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[1][2] = 0.385;
            miller_value[1][2] = 1.5;
            horiz_dielectric_constant[1][2] = 2.214;
            vert_dielectric_constant[1][2] = 3.9;
            wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
                ild_thickness[1][2], miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
                fringe_cap);
          }
        else { // wire data from ITRS 2012 reports, by Woojoo Lee, USC.
          wire_pitch[0][0]        = 0.112;
          wire_pitch[0][1]        = 0.112;
          wire_pitch[0][2]        = 0.18;
          wire_r_per_micron[0][0] = 6.55;
          wire_r_per_micron[0][1] = 6.55;
          wire_r_per_micron[0][2] = 1.09;
          wire_r_per_micron[1][0] = 6.55;
          wire_r_per_micron[1][1] = 6.55;
          wire_r_per_micron[1][2] = 1.09;
          wire_c_per_micron[0][0] = 2.00e-16;
          wire_c_per_micron[0][1] = 2.00e-16;
          wire_c_per_micron[0][2] = 2.10e-16;
          wire_c_per_micron[1][0] = 2.10e-16;
          wire_c_per_micron[1][1] = 2.10e-16;
          wire_c_per_micron[1][2] = 2.30e-16;
        }
        //Nominal projections for commodity DRAM wordline/bitline
        wire_pitch[1][3] = 2 * 0.032;//micron
        wire_c_per_micron[1][3] = 31e-15 / (256 * 2 * 0.032);//F/micron
        wire_r_per_micron[1][3] = 12 / 0.032;//ohm/micron
      }
      else if (tech == 22) {
        if ( !g_ip->is_itrs2012 ) { // wire data from Ron Ho's PhD Thesis, Stanford, 2003.
          //Aggressive projections.
          wire_pitch[0][0] = 2.5 * g_ip->wire_F_sz_um;//local
          aspect_ratio[0][0] = 3.0;
          wire_width = wire_pitch[0][0] / 2;
          wire_thickness = aspect_ratio[0][0] * wire_width;
          wire_spacing = wire_pitch[0][0] - wire_width;
          barrier_thickness = 0;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[0][0] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
               wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][0] = 0.15;
          miller_value[0][0] = 1.5;
          horiz_dielectric_constant[0][0] = 1.414;
          vert_dielectric_constant[0][0] = 3.9;
          fringe_cap = 0.115e-15;
          wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
            ild_thickness[0][0], miller_value[0][0], horiz_dielectric_constant[0][0],
			vert_dielectric_constant[0][0],
            fringe_cap);
          
          wire_pitch[0][1] = 4 * g_ip->wire_F_sz_um;//semi-global
          wire_width = wire_pitch[0][1] / 2;
          aspect_ratio[0][1] = 3.0;
          wire_thickness = aspect_ratio[0][1] * wire_width;
          wire_spacing = wire_pitch[0][1] - wire_width;
          wire_r_per_micron[0][1] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
               wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][1] = 0.15;
          miller_value[0][1] = 1.5;
          horiz_dielectric_constant[0][1] = 1.414;
          vert_dielectric_constant[0][1] = 3.9;
          wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
            ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1],
			vert_dielectric_constant[0][1],
            fringe_cap);
          
          wire_pitch[0][2] = 8 * g_ip->wire_F_sz_um;//global
          aspect_ratio[0][2] = 3.0;
          wire_width = wire_pitch[0][2] / 2;
          wire_thickness = aspect_ratio[0][2] * wire_width;
          wire_spacing = wire_pitch[0][2] - wire_width;
          wire_r_per_micron[0][2] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
          	  wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][2] = 0.3;
          miller_value[0][2] = 1.5;
          horiz_dielectric_constant[0][2] = 1.414;
          vert_dielectric_constant[0][2] = 3.9;
          wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
          	  ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2],
			  vert_dielectric_constant[0][2],
          	  fringe_cap);
          
          //Conservative projections
          wire_pitch[1][0] = 2.5 * g_ip->wire_F_sz_um;
          aspect_ratio[1][0] = 2.0;
          wire_width = wire_pitch[1][0] / 2;
          wire_thickness = aspect_ratio[1][0] * wire_width;
          wire_spacing = wire_pitch[1][0] - wire_width;
          barrier_thickness = 0.003;
          dishing_thickness = 0;
          alpha_scatter = 1.05;
          wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
            wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][0] = 0.15;
          miller_value[1][0] = 1.5;
          horiz_dielectric_constant[1][0] = 2.104;
          vert_dielectric_constant[1][0] = 3.9;
          fringe_cap = 0.115e-15;
          wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
            ild_thickness[1][0], miller_value[1][0], horiz_dielectric_constant[1][0],
			vert_dielectric_constant[1][0],
            fringe_cap);

          wire_pitch[1][1] = 4 * g_ip->wire_F_sz_um;
          wire_width = wire_pitch[1][1] / 2;
          aspect_ratio[1][1] = 2.0;
          wire_thickness = aspect_ratio[1][1] * wire_width;
          wire_spacing = wire_pitch[1][1] - wire_width;
          wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
            wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][1] = 0.15;
          miller_value[1][1] = 1.5;
          horiz_dielectric_constant[1][1] = 2.104;
          vert_dielectric_constant[1][1] = 3.9;
          wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
            ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1], vert_dielectric_constant[1][1],
            fringe_cap);

          wire_pitch[1][2] = 8 * g_ip->wire_F_sz_um;
          aspect_ratio[1][2] = 2.2;
          wire_width = wire_pitch[1][2] / 2;
          wire_thickness = aspect_ratio[1][2] * wire_width;
          wire_spacing = wire_pitch[1][2] - wire_width;
          dishing_thickness = 0.1 *  wire_thickness;
          wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
          		wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][2] = 0.275;
          miller_value[1][2] = 1.5;
          horiz_dielectric_constant[1][2] = 2.104;
          vert_dielectric_constant[1][2] = 3.9;
          wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
          		ild_thickness[1][2], miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
          		fringe_cap);

        }

        else { // wire data from ITRS 2012 reports, by Woojoo Lee, USC.
          wire_pitch[0][0]        = 0.076;
          wire_pitch[0][1]        = 0.076;
          wire_pitch[0][2]        = 0.13;
          wire_r_per_micron[0][0] = 17.24;
          wire_r_per_micron[0][1] = 17.23;
          wire_r_per_micron[0][2] = 1.92;
          wire_r_per_micron[1][0] = 17.24;
          wire_r_per_micron[1][1] = 17.23;
          wire_r_per_micron[1][2] = 3.58;
          wire_c_per_micron[0][0] = 1.90e-16;
          wire_c_per_micron[0][1] = 1.70e-16;
          wire_c_per_micron[0][2] = 2.00e-16;
          wire_c_per_micron[1][0] = 2.10e-16;
          wire_c_per_micron[1][1] = 1.90e-16;
          wire_c_per_micron[1][2] = 2.30e-16;
        }
        
        //Nominal projections for commodity DRAM wordline/bitline
        wire_pitch[1][3] = 2 * 0.022;//micron
        wire_c_per_micron[1][3] = 26.6e-15 / (256 * 2 * 0.022);//F/micron  // Alireza: scaling
        wire_r_per_micron[1][3] = 12 / 0.022;//ohm/micron
      }
      else if (tech == 16)// || tech == 14) { // Alireza2
      {
    	  if ( !g_ip->is_itrs2012 ) { // wire data from Ron Ho's PhD Thesis, Stanford, 2003.
            //Aggressive projections.
            wire_pitch[0][0] = 2.5 * g_ip->F_sz_um;//local
            aspect_ratio[0][0] = 3.0;
            wire_width = wire_pitch[0][0] / 2;
            wire_thickness = aspect_ratio[0][0] * wire_width;
            wire_spacing = wire_pitch[0][0] - wire_width;
            barrier_thickness = 0;
            dishing_thickness = 0;
            alpha_scatter = 1;
            wire_r_per_micron[0][0] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[0][0] = 0.108;
            miller_value[0][0] = 1.5;
            horiz_dielectric_constant[0][0] = 1.202;
            vert_dielectric_constant[0][0] = 3.9;
            fringe_cap = 0.115e-15;
            wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][0], miller_value[0][0], horiz_dielectric_constant[0][0], vert_dielectric_constant[0][0],
              fringe_cap);

            wire_pitch[0][1] = 4 * g_ip->F_sz_um;//semi-global
            aspect_ratio[0][1] = 3.0;
            wire_width = wire_pitch[0][1] / 2;
            wire_thickness = aspect_ratio[0][1] * wire_width;
            wire_spacing = wire_pitch[0][1] - wire_width;
            wire_r_per_micron[0][1] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[0][1] = 0.108;
            miller_value[0][1] = 1.5;
            horiz_dielectric_constant[0][1] = 1.202;
            vert_dielectric_constant[0][1] = 3.9;
            wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1], vert_dielectric_constant[0][1],
              fringe_cap);

            wire_pitch[0][2] = 8 * g_ip->F_sz_um;//global
            aspect_ratio[0][2] = 3.0;
            wire_width = wire_pitch[0][2] / 2;
            wire_thickness = aspect_ratio[0][2] * wire_width;
            wire_spacing = wire_pitch[0][2] - wire_width;
            wire_r_per_micron[0][2] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
          		  wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[0][2] = 0.216;
            miller_value[0][2] = 1.5;
            horiz_dielectric_constant[0][2] = 1.202;
            vert_dielectric_constant[0][2] = 3.9;
            wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
          		  ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2], vert_dielectric_constant[0][2],
          		  fringe_cap);

            //Conservative projections
            wire_pitch[1][0] = 2.5 * g_ip->F_sz_um;
            aspect_ratio[1][0] = 2.0;
            wire_width = wire_pitch[1][0] / 2;
            wire_thickness = aspect_ratio[1][0] * wire_width;
            wire_spacing = wire_pitch[1][0] - wire_width;
            barrier_thickness = 0.002;
            dishing_thickness = 0;
            alpha_scatter = 1.05;
            wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[1][0] = 0.108;
            miller_value[1][0] = 1.5;
            horiz_dielectric_constant[1][0] = 1.998;
            vert_dielectric_constant[1][0] = 3.9;
            fringe_cap = 0.115e-15;
            wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][0], miller_value[1][0], horiz_dielectric_constant[1][0], vert_dielectric_constant[1][0],
              fringe_cap);

            wire_pitch[1][1] = 4 * g_ip->F_sz_um;
            wire_width = wire_pitch[1][1] / 2;
            aspect_ratio[1][1] = 2.0;
            wire_thickness = aspect_ratio[1][1] * wire_width;
            wire_spacing = wire_pitch[1][1] - wire_width;
            wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
            ild_thickness[1][1] = 0.108;
            miller_value[1][1] = 1.5;
            horiz_dielectric_constant[1][1] = 1.998;
            vert_dielectric_constant[1][1] = 3.9;
              wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1], vert_dielectric_constant[1][1],
              fringe_cap);

              wire_pitch[1][2] = 8 * g_ip->F_sz_um;
              aspect_ratio[1][2] = 2.2;
              wire_width = wire_pitch[1][2] / 2;
              wire_thickness = aspect_ratio[1][2] * wire_width;
              wire_spacing = wire_pitch[1][2] - wire_width;
              dishing_thickness = 0.1 *  wire_thickness;
              wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
              		wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
              ild_thickness[1][2] = 0.198;
              miller_value[1][2] = 1.5;
              horiz_dielectric_constant[1][2] = 1.998;
              vert_dielectric_constant[1][2] = 3.9;
              wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              		ild_thickness[1][2], miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
              		fringe_cap);
        }
        else { // wire data from ITRS 2012 reports, by Woojoo Lee, USC.
          wire_pitch[0][0]        = 0.054;
          wire_pitch[0][1]        = 0.054;
          wire_pitch[0][2]        = 0.081;
          wire_r_per_micron[0][0] = 40.647;
          wire_r_per_micron[0][1] = 40.647;
          wire_r_per_micron[0][2] = 4.95;
          wire_r_per_micron[1][0] = 40.647;
          wire_r_per_micron[1][1] = 40.647;
          wire_r_per_micron[1][2] = 10.838;
          wire_c_per_micron[0][0] = 1.80e-16;
          wire_c_per_micron[0][1] = 1.60e-16;
          wire_c_per_micron[0][2] = 1.80e-16;
          wire_c_per_micron[1][0] = 2.00e-16;
          wire_c_per_micron[1][1] = 1.90e-16;
          wire_c_per_micron[1][2] = 2.20e-16;
        }
        
        //Nominal projections for commodity DRAM wordline/bitline
        wire_pitch[1][3] = 2 * 0.016;//micron
        wire_c_per_micron[1][3] = 23.5e-15 / (256 * 2 * 0.016);//F/micron
        wire_r_per_micron[1][3] = 12 / 0.016;//ohm/micron
      }
      else if (tech == 10) { // Alireza
        if ( !g_ip->is_itrs2012 ) { // wire data from Ron Ho's PhD Thesis, Stanford, 2003.
          //Aggressive projections.
          wire_pitch[0][0] = 2.5 * g_ip->wire_F_sz_um;
          aspect_ratio[0][0] = 3.0;
          wire_width = wire_pitch[0][0] / 2;
          wire_thickness = aspect_ratio[0][0] * wire_width;
          wire_spacing = wire_pitch[0][0] - wire_width;
          barrier_thickness = 0;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[0][0] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][0] = 0.078;
          miller_value[0][0] = 1.5;
          horiz_dielectric_constant[0][0] = 1.022;
          vert_dielectric_constant[0][0] = 3.9;
          fringe_cap = 0.115e-15; 
          wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[0][0], miller_value[0][0], horiz_dielectric_constant[0][0],
			  vert_dielectric_constant[0][0],
              fringe_cap);
          
          wire_pitch[0][1] = 4 * g_ip->wire_F_sz_um;
          wire_width = wire_pitch[0][1] / 2;
          aspect_ratio[0][1] = 3.0;
          wire_thickness = aspect_ratio[0][1] * wire_width;
          wire_spacing = wire_pitch[0][1] - wire_width;
          wire_r_per_micron[0][1] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][1] = 0.078;
          miller_value[0][1] = 1.5;
          horiz_dielectric_constant[0][1] = 1.022;
          vert_dielectric_constant[0][1] = 3.9;
          wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1],
			  vert_dielectric_constant[0][1],
              fringe_cap);
          
          wire_pitch[0][2] = 8 * g_ip->wire_F_sz_um;
          aspect_ratio[0][2] = 3.0;
          wire_width = wire_pitch[0][2] / 2;
          wire_thickness = aspect_ratio[0][2] * wire_width;
          wire_spacing = wire_pitch[0][2] - wire_width;
          wire_r_per_micron[0][2] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][2] = 0.156;
          miller_value[0][2] = 1.5;
          horiz_dielectric_constant[0][2] = 1.022;
          vert_dielectric_constant[0][2] = 3.9;
          wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2], vert_dielectric_constant[0][2],
              fringe_cap);
          
          //Conservative projections
          wire_pitch[1][0] = 2.5 * g_ip->wire_F_sz_um;
          aspect_ratio[1][0]  = 2.0;
          wire_width = wire_pitch[1][0] / 2;
          wire_thickness = aspect_ratio[1][0] * wire_width;
          wire_spacing = wire_pitch[1][0] - wire_width;
          barrier_thickness = 0.002;
          dishing_thickness = 0;
          alpha_scatter = 1.05;
          wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][0]  = 0.078;
          miller_value[1][0]  = 1.5;
          horiz_dielectric_constant[1][0]  = 1.899;
          vert_dielectric_constant[1][0]  = 3.9;
          fringe_cap = 0.115e-15; 
          wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[1][0] , miller_value[1][0] , horiz_dielectric_constant[1][0] , vert_dielectric_constant[1][0] ,
              fringe_cap);
          
          wire_pitch[1][1] = 4 * g_ip->wire_F_sz_um;
          aspect_ratio[1][1]  = 2.0;
          wire_width = wire_pitch[1][1] / 2;
          wire_thickness = aspect_ratio[1][1]  * wire_width;
          wire_spacing = wire_pitch[1][1] - wire_width;
          wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][1]  = 0.078;
          miller_value[1][1]  = 1.5;
          horiz_dielectric_constant[1][1]  = 1.899;
          vert_dielectric_constant[1][1]  = 3.9;
          wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1] , vert_dielectric_constant[1][1] ,
              fringe_cap);
          
          wire_pitch[1][2] = 8 * g_ip->wire_F_sz_um;
          aspect_ratio[1][2] = 2.2;
          wire_width = wire_pitch[1][2] / 2;
          wire_thickness = aspect_ratio[1][2] * wire_width;
          wire_spacing = wire_pitch[1][2] - wire_width;
          dishing_thickness = 0.1 *  wire_thickness; 
          wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][2] = 0.143;
          miller_value[1][2]  = 1.5;
          horiz_dielectric_constant[1][2]  = 1.899;
          vert_dielectric_constant[1][2]  = 3.9;
          wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[1][2], miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
              fringe_cap);
        }
        else { // wire data from ITRS 2012 reports, by Woojoo Lee, USC.
          wire_pitch[0][0]        = 0.042;
          wire_pitch[0][1]        = 0.042;
          wire_pitch[0][2]        = 0.063;
          wire_r_per_micron[0][0] = 78.888;
          wire_r_per_micron[0][1] = 78.888;
          wire_r_per_micron[0][2] = 8.18;
          wire_r_per_micron[1][0] = 78.888;
          wire_r_per_micron[1][1] = 78.888;
          wire_r_per_micron[1][2] = 20.759;
          wire_c_per_micron[0][0] = 1.80e-16;
          wire_c_per_micron[0][1] = 1.60e-16;
          wire_c_per_micron[0][2] = 1.80e-16;
          wire_c_per_micron[1][0] = 2.00e-16;
          wire_c_per_micron[1][1] = 1.90e-16;
          wire_c_per_micron[1][2] = 2.20e-16;
        }
        
        //Nominal projections for commodity DRAM wordline/bitline
        wire_pitch[1][3] = 2 * 0.010;//micron
        wire_c_per_micron[1][3] = 20.4e-15 / (256 * 2 * 0.010);//F/micron
        wire_r_per_micron[1][3] = 12 / 0.010;//ohm/micron
      }
      else if (tech == 7 || tech == 14)	//divya including tech ==14 here {
      {
    	  if ( !g_ip->is_itrs2012 ) { // wire data from Ron Ho's PhD Thesis, Stanford, 2003.
          //Aggressive projections.
        	//Divya adding for ASAP7 wire data. If itrs_2012 = false and asap7 = true . *** ONLY FOR AGGRESSIVE PROJECTIONS ***
        	if(g_ip->is_asap7) { //Local wires
//        		cout << "technology.cc:: wire : " << g_ip->wire_F_sz_um << ", tech: " << tech << ", asap7" << endl;
        		wire_pitch[0][0] = 0.036;	//Local wires
        		wire_width = 0.018;
			    wire_spacing = 0.018;
			    wire_thickness = 0.036;
        		aspect_ratio[0][0]  = 2.0;
        	}
        	else { //Rohno 2003 PhD
			  wire_pitch[0][0] = 2.5 * g_ip->wire_F_sz_um;
			  aspect_ratio[0][0]  = 3.0;
			  wire_width = wire_pitch[0][0] / 2;
			  wire_thickness = aspect_ratio[0][0] * wire_width;
			  wire_spacing = wire_pitch[0][0] - wire_width;
        	}
        	//divya end
          barrier_thickness = 0;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[0][0] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][0]  = 0.065;
          miller_value[0][0]  = 1.5;
          horiz_dielectric_constant[0][0]  = 0.864;
          vert_dielectric_constant[0][0]  = 3.9;
          fringe_cap = 0.115e-15; 
          wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[0][0] , miller_value[0][0] , horiz_dielectric_constant[0][0] , vert_dielectric_constant[0][0] ,
              fringe_cap);
          
          //Divya adding for ASAP7 wire data. If itrs_2012 = false and asap7 = true
          if(g_ip->is_asap7) { //semi-global wires
        	  wire_pitch[0][1] = 0.048;	//semi-global wires
			  wire_width = 0.024;
			  wire_spacing = 0.024;
			  wire_thickness = 0.048;
			  aspect_ratio[0][1] = 2.0;
          } else {
          wire_pitch[0][1] = 4 * g_ip->wire_F_sz_um;
		  aspect_ratio[0][1]  = 3.0;
          wire_width = wire_pitch[0][1] / 2;
          wire_thickness = aspect_ratio[0][1] * wire_width;
          wire_spacing = wire_pitch[0][1] - wire_width;
          }
          //divya end
          ild_thickness[0][1]  = 0.065;
          miller_value[0][1]  = 1.5;
          horiz_dielectric_constant[0][1]  = 0.864;
          vert_dielectric_constant[0][1]  = 3.9;

          wire_r_per_micron[0][1] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1], vert_dielectric_constant[0][1],
              fringe_cap);
          
          //Divya adding for ASAP7 wire data. If itrs_2012 = false and asap7 = true
		   if(g_ip->is_asap7) { //Global wires
			  wire_pitch[0][2] = 0.08;	//global wires
			  wire_width = 0.04;
			  wire_spacing = 0.032;
			  wire_thickness = 0.08;
			  aspect_ratio[0][2] = 2.0;
		   } else {
			  wire_pitch[0][2] = 8 * g_ip->wire_F_sz_um;
			  aspect_ratio[0][2] = 3.0;
			  wire_width = wire_pitch[0][2] / 2;
			  wire_thickness = aspect_ratio[0][2] * wire_width;
			  wire_spacing = wire_pitch[0][2] - wire_width;
           }
		   //divya end
	          miller_value[0][2]  = 1.5;
	          horiz_dielectric_constant[0][2]  = 0.864;
	          vert_dielectric_constant[0][2]  = 3.9;

	       wire_r_per_micron[0][2] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][2] = 0.130;
          wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2], vert_dielectric_constant[0][2],
              fringe_cap);
  /*
          cout << " wire_r_per_micron[0][0]: " <<  wire_r_per_micron[0][0] <<
        		  ", wire_c_per_micron[0][0]: " << wire_c_per_micron[0][0] <<
				  ", wire_r_per_micron[0][1]: " << wire_r_per_micron[0][1] <<
				  ", wire_c_per_micron[0][1]: " << wire_c_per_micron[0][1] <<
				  ", wire_r_per_micron[0][2]: " << wire_r_per_micron[0][2] <<
				   ", wire_c_per_micron[0][2]: " << wire_c_per_micron[0][2] << endl;
*/
          //Conservative projections
          wire_pitch[1][0] = 2.5 * g_ip->wire_F_sz_um;
          aspect_ratio[1][0] = 2.0;
          wire_width = wire_pitch[1][0] / 2;
          wire_thickness = aspect_ratio[1][0] * wire_width;
          wire_spacing = wire_pitch[1][0] - wire_width;
          barrier_thickness = 0.002;
          dishing_thickness = 0;
          alpha_scatter = 1.05;
          wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][0] = 0.065;
          miller_value[1][0] = 1.5;
          horiz_dielectric_constant[1][0] = 1.884;
          vert_dielectric_constant[1][0] = 3.9;
          fringe_cap = 0.115e-15; 
          wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[1][0], miller_value[1][0], horiz_dielectric_constant[1][0],
			  vert_dielectric_constant[1][0],
              fringe_cap);

          wire_pitch[1][1] = 4 * g_ip->wire_F_sz_um;
          aspect_ratio[1][1] = 2.0;
         wire_width = wire_pitch[1][1] / 2;
          wire_thickness = aspect_ratio[1][1] * wire_width;
          wire_spacing = wire_pitch[1][1] - wire_width;
          wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][1] = 0.065;
          miller_value[1][1] = 1.5;
          horiz_dielectric_constant[1][1] = 1.884;
          vert_dielectric_constant[1][1] = 3.9;
         wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1],
			  vert_dielectric_constant[1][1],
              fringe_cap);

          wire_pitch[1][2] = 8 * g_ip->wire_F_sz_um;
          aspect_ratio[1][2] = 2.2;
          wire_width = wire_pitch[1][2] / 2;
          wire_thickness = aspect_ratio[1][2] * wire_width;
          wire_spacing = wire_pitch[1][2] - wire_width;
          dishing_thickness = 0.1 *  wire_thickness; 
          wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][2] = 0.103;
          miller_value[1][2] = 1.5;
          horiz_dielectric_constant[1][2] = 1.884;
          vert_dielectric_constant[1][2] = 3.9;
          wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[1][2], miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
              fringe_cap);

//---------------------------------------------------------------------------------------
//---------------------------------------------------------------------------------------
//---------------------------------------------------------------------------------------
        }

        else { // wire data from ITRS 2012 reports, by Woojoo Lee, USC.
          wire_pitch[0][0]        = 0.034;
          wire_pitch[0][1]        = 0.034;
          wire_pitch[0][2]        = 0.051;
          wire_r_per_micron[0][0] = 129.066;
          wire_r_per_micron[0][1] = 129.066;
          wire_r_per_micron[0][2] = 12.49;
          wire_r_per_micron[1][0] = 129.066;
          wire_r_per_micron[1][1] = 129.066;
          wire_r_per_micron[1][2] = 37.264;
          wire_c_per_micron[0][0] = 1.80e-16;
          wire_c_per_micron[0][1] = 1.50e-16;
          wire_c_per_micron[0][2] = 1.70e-16;
          wire_c_per_micron[1][0] = 2.00e-16;
          wire_c_per_micron[1][1] = 1.80e-16;
          wire_c_per_micron[1][2] = 2.00e-16;
        }
        
        //Nominal projections for commodity DRAM wordline/bitline
        wire_pitch[1][3] = 2 * 0.007;//micron
        wire_c_per_micron[1][3] = 17.8e-15 / (256 * 2 * 0.007);//F/micron
        wire_r_per_micron[1][3] = 12 / 0.007;//ohm/micron
      }
      else if (tech == 5) {
        if ( !g_ip->is_itrs2012 ) { // wire data from Ron Ho's PhD Thesis, Stanford, 2003.
          //Aggressive projections.
          wire_pitch[0][0] = 2.5 * g_ip->wire_F_sz_um;
          aspect_ratio[0][0] = 3.0;
          wire_width = wire_pitch[0][0] / 2;
          wire_thickness = aspect_ratio[0][0] * wire_width;
          wire_spacing = wire_pitch[0][0] - wire_width;
          barrier_thickness = 0;
          dishing_thickness = 0;
          alpha_scatter = 1;
          wire_r_per_micron[0][0] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][0] = 0.065;
          miller_value[0][0] = 1.5;
          horiz_dielectric_constant[0][0] = 0.864;
          vert_dielectric_constant[0][0] = 3.9;
          fringe_cap = 0.115e-15; 
          wire_c_per_micron[0][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[0][0], miller_value[0][0], horiz_dielectric_constant[0][0], vert_dielectric_constant[0][0],
              fringe_cap);
          
          wire_pitch[0][1] = 4 * g_ip->wire_F_sz_um;
          aspect_ratio[0][1] = 3.0;
          wire_width = wire_pitch[0][1] / 2;
          wire_thickness = aspect_ratio[0][1] * wire_width;
          wire_spacing = wire_pitch[0][1] - wire_width;
          wire_r_per_micron[0][1] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][1] = 0.065;
          miller_value[0][1] = 1.5;
          horiz_dielectric_constant[0][1] = 0.864;
          vert_dielectric_constant[0][1] = 3.9;
         wire_c_per_micron[0][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing,
              ild_thickness[0][1], miller_value[0][1], horiz_dielectric_constant[0][1], vert_dielectric_constant[0][1],
              fringe_cap);
          
          wire_pitch[0][2] = 8 * g_ip->wire_F_sz_um;
          aspect_ratio[0][2] = 3.0;
          wire_width = wire_pitch[0][2] / 2;
          wire_thickness = aspect_ratio[0][2] * wire_width;
          wire_spacing = wire_pitch[0][2] - wire_width;
          wire_r_per_micron[0][2] = wire_resistance(BULK_CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[0][2] = 0.130;
          miller_value[0][2] = 1.5;
          horiz_dielectric_constant[0][2] = 0.864;
          vert_dielectric_constant[0][2] = 3.9;
          wire_c_per_micron[0][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[0][2], miller_value[0][2], horiz_dielectric_constant[0][2], vert_dielectric_constant[0][2],
              fringe_cap);
          
          //Conservative projections
          wire_pitch[1][0] = 2.5 * g_ip->wire_F_sz_um;
          aspect_ratio[1][0] = 2.0;
          wire_width = wire_pitch[1][0] / 2;
          wire_thickness = aspect_ratio[1][0] * wire_width;
          wire_spacing = wire_pitch[1][0] - wire_width;
          barrier_thickness = 0.002;
          dishing_thickness = 0;
          alpha_scatter = 1.05;
          wire_r_per_micron[1][0] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][0] = 0.065;
          miller_value[1][0] = 1.5;
          horiz_dielectric_constant[1][0] = 1.884;
          vert_dielectric_constant[1][0] = 3.9;
          fringe_cap = 0.115e-15; 
          wire_c_per_micron[1][0] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[1][0], miller_value[1][0], horiz_dielectric_constant[1][0], vert_dielectric_constant[1][0],
              fringe_cap);
          
          wire_pitch[1][1] = 4 * g_ip->wire_F_sz_um;
          aspect_ratio[1][1] = 2.0;
          wire_width = wire_pitch[1][1] / 2;
          wire_thickness = aspect_ratio[1][1] * wire_width;
          wire_spacing = wire_pitch[1][1] - wire_width;
          wire_r_per_micron[1][1] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][1] = 0.065;
          miller_value[1][1] = 1.5;
          horiz_dielectric_constant[1][1] = 1.884;
          vert_dielectric_constant[1][1] = 3.9;
          wire_c_per_micron[1][1] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[1][1], miller_value[1][1], horiz_dielectric_constant[1][1], vert_dielectric_constant[1][1],
              fringe_cap);
          
          wire_pitch[1][2] = 8 * g_ip->wire_F_sz_um;
          aspect_ratio[1][2] = 2.2;
          wire_width = wire_pitch[1][2] / 2;
          wire_thickness = aspect_ratio[1][2] * wire_width;
          wire_spacing = wire_pitch[1][2] - wire_width;
          dishing_thickness = 0.1 *  wire_thickness; 
          wire_r_per_micron[1][2] = wire_resistance(CU_RESISTIVITY, wire_width,
              wire_thickness, barrier_thickness, dishing_thickness, alpha_scatter);
          ild_thickness[1][2] = 0.103;
          miller_value[1][2] = 1.5;
          horiz_dielectric_constant[1][2] = 1.884;
          vert_dielectric_constant[1][2] = 3.9;
          wire_c_per_micron[1][2] = wire_capacitance(wire_width, wire_thickness, wire_spacing, 
              ild_thickness[1][2], miller_value[1][2], horiz_dielectric_constant[1][2], vert_dielectric_constant[1][2],
              fringe_cap);
        }
        else { // wire data from ITRS 2012 reports, by Woojoo Lee, USC.
          wire_pitch[0][0]        = 0.027;
          wire_pitch[0][1]        = 0.027;
          wire_pitch[0][2]        = 0.04;
          wire_r_per_micron[0][0] = 241.701;
          wire_r_per_micron[0][1] = 241.701;
          wire_r_per_micron[0][2] = 20.29;
          wire_r_per_micron[1][0] = 241.701;
          wire_r_per_micron[1][1] = 241.701;
          wire_r_per_micron[1][2] = 73.504;
          wire_c_per_micron[0][0] = 1.60e-16;
          wire_c_per_micron[0][1] = 1.50e-16;
          wire_c_per_micron[0][2] = 1.50e-16;
          wire_c_per_micron[1][0] = 1.80e-16;
          wire_c_per_micron[1][1] = 1.80e-16;
          wire_c_per_micron[1][2] = 1.80e-16;
        }
        
        //Nominal projections for commodity DRAM wordline/bitline
        wire_pitch[1][3] = 2 * 0.005;//micron
        wire_c_per_micron[1][3] = 17.8e-15 / (256 * 2 * 0.005);//F/micron
        wire_r_per_micron[1][3] = 12 / 0.005;//ohm/micron
      }
      
		// TO DO: Update "[(ram_cell_tech_type == comm_dram)?3:0]"
      g_tp.wire_local.pitch    += curr_alpha * wire_pitch[g_ip->ic_proj_type][(ram_cell_tech_type == comm_dram)?3:0];
      g_tp.wire_local.R_per_um += curr_alpha * wire_r_per_micron[g_ip->ic_proj_type][(ram_cell_tech_type == comm_dram)?3:0];
      g_tp.wire_local.C_per_um += curr_alpha * wire_c_per_micron[g_ip->ic_proj_type][(ram_cell_tech_type == comm_dram)?3:0];
      g_tp.wire_local.aspect_ratio  += curr_alpha * aspect_ratio[g_ip->ic_proj_type][(ram_cell_tech_type == comm_dram)?3:0];
      g_tp.wire_local.ild_thickness += curr_alpha * ild_thickness[g_ip->ic_proj_type][(ram_cell_tech_type == comm_dram)?3:0];
      g_tp.wire_local.miller_value   += curr_alpha * miller_value[g_ip->ic_proj_type][(ram_cell_tech_type == comm_dram)?3:0];
      g_tp.wire_local.horiz_dielectric_constant += curr_alpha* horiz_dielectric_constant[g_ip->ic_proj_type][(ram_cell_tech_type == comm_dram)?3:0];
      g_tp.wire_local.vert_dielectric_constant  += curr_alpha* vert_dielectric_constant [g_ip->ic_proj_type][(ram_cell_tech_type == comm_dram)?3:0];
      
      g_tp.wire_inside_mat.pitch     += curr_alpha * wire_pitch[g_ip->ic_proj_type][g_ip->wire_is_mat_type];
      g_tp.wire_inside_mat.R_per_um  += curr_alpha * wire_r_per_micron[g_ip->ic_proj_type][g_ip->wire_is_mat_type];
      g_tp.wire_inside_mat.C_per_um  += curr_alpha * wire_c_per_micron[g_ip->ic_proj_type][g_ip->wire_is_mat_type];
      g_tp.wire_inside_mat.aspect_ratio  += curr_alpha * aspect_ratio[g_ip->ic_proj_type][g_ip->wire_is_mat_type];
      g_tp.wire_inside_mat.ild_thickness += curr_alpha * ild_thickness[g_ip->ic_proj_type][g_ip->wire_is_mat_type];
      g_tp.wire_inside_mat.miller_value   += curr_alpha * miller_value[g_ip->ic_proj_type][g_ip->wire_is_mat_type];
      g_tp.wire_inside_mat.horiz_dielectric_constant += curr_alpha* horiz_dielectric_constant[g_ip->ic_proj_type][g_ip->wire_is_mat_type];
      g_tp.wire_inside_mat.vert_dielectric_constant  += curr_alpha* vert_dielectric_constant [g_ip->ic_proj_type][g_ip->wire_is_mat_type];
      
      g_tp.wire_outside_mat.pitch    += curr_alpha * wire_pitch[g_ip->ic_proj_type][g_ip->wire_os_mat_type];
      g_tp.wire_outside_mat.R_per_um += curr_alpha * wire_r_per_micron[g_ip->ic_proj_type][g_ip->wire_os_mat_type];
      g_tp.wire_outside_mat.C_per_um += curr_alpha * wire_c_per_micron[g_ip->ic_proj_type][g_ip->wire_os_mat_type];
      g_tp.wire_outside_mat.aspect_ratio  += curr_alpha * aspect_ratio[g_ip->ic_proj_type][g_ip->wire_os_mat_type];
      g_tp.wire_outside_mat.ild_thickness += curr_alpha * ild_thickness[g_ip->ic_proj_type][g_ip->wire_os_mat_type];
      g_tp.wire_outside_mat.miller_value   += curr_alpha * miller_value[g_ip->ic_proj_type][g_ip->wire_os_mat_type];
      g_tp.wire_outside_mat.horiz_dielectric_constant += curr_alpha* horiz_dielectric_constant[g_ip->ic_proj_type][g_ip->wire_os_mat_type];
      g_tp.wire_outside_mat.vert_dielectric_constant  += curr_alpha* vert_dielectric_constant [g_ip->ic_proj_type][g_ip->wire_os_mat_type];

      g_tp.unit_len_wire_del = g_tp.wire_inside_mat.R_per_um * g_tp.wire_inside_mat.C_per_um / 2;
    }
	//-------------------- interconnect (wire) parameters end ----------------------------

	 
	g_tp.sense_delay = SENSE_AMP_D;
	g_tp.sense_dy_power = SENSE_AMP_P;
/*
 	g_tp.horiz_dielectric_constant = horiz_dielectric_constant;
	g_tp.vert_dielectric_constant = vert_dielectric_constant;
	g_tp.aspect_ratio = aspect_ratio;
	g_tp.miller_value = miller_value;
*/
	  g_tp.fringe_cap = fringe_cap;

	double rd = tr_R_on(g_tp.min_w_nmos_, NCH, 1);
	double p_to_n_sizing_r = pmos_to_nmos_sz_ratio();
	double c_load = gate_C(g_tp.min_w_nmos_ * (1 + p_to_n_sizing_r), 0.0);
	double tf = rd * c_load;
	g_tp.kinv = horowitz(0, tf, 0.5, 0.5, RISE);
	double KLOAD = 1;
	c_load = KLOAD * (drain_C_(g_tp.min_w_nmos_, NCH, 1, 1, g_tp.cell_h_def) + 
				drain_C_(g_tp.min_w_nmos_ * p_to_n_sizing_r, PCH, 1, 1, g_tp.cell_h_def) +
				gate_C(g_tp.min_w_nmos_ * 4 * (1 + p_to_n_sizing_r), 0.0));
	tf = rd * c_load;
	g_tp.FO4 = horowitz(0, tf, 0.5, 0.5, RISE);
}
