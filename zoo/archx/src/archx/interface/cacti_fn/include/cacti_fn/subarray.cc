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


#include <iostream>
#include <math.h>
#include <assert.h>

#include "subarray.h"


Subarray::Subarray(const DynamicParameter & dp_, bool is_fa_):
  dp(dp_), num_rows(dp.num_r_subarray), num_cols(dp.num_c_subarray),
  num_cols_fa_cam(dp.tag_num_c_subarray), num_cols_fa_ram(dp.data_num_c_subarray),
  cell(dp.cell), cam_cell(dp.cam_cell), is_fa(is_fa_)
{
    if(cell.h < 0) //divya
  	       cout << "subarray.cc subarray() cell.h : " << cell.h << ", cell.w : " << cell.w << "is_fa : " << is_fa << endl;

    if (!(is_fa || dp.pure_cam))
    {
  	  num_cols +=(g_ip->add_ecc_b_ ? (int)ceil(num_cols / num_bits_per_ecc_b_) : 0);   // ECC overhead
  	  uint32_t ram_num_cells_wl_stitching =
  		  (dp.ram_cell_tech_type == lp_dram)   ? dram_num_cells_wl_stitching_ :
  	  (dp.ram_cell_tech_type == comm_dram) ? comm_dram_num_cells_wl_stitching_ : sram_num_cells_wl_stitching_;

  	  area.h = cell.h * num_rows;

  	  area.w = cell.w * num_cols +
  	  ceil(num_cols / ram_num_cells_wl_stitching) * g_tp.ram_wl_stitching_overhead_;  // stitching overhead
    }
  else  // cam fa
  {
/*    // it is assumed that the transistor size of a CAM cell is linearly scaled from 0.8um process
    double CAM2x2_h_1p = 61 * g_ip->F_sz_um;  // 48.8um in 0.8um process
    double CAM2x2_w_1p = 56 * g_ip->F_sz_um;  // 44.8um in 0.8um process
    double fa_h_incr_per_first_rw_or_wr_port_ = 20 * g_ip->F_sz_um;
    double fa_h_incr_per_later_rw_or_wr_port_ = 20 * g_ip->F_sz_um;
    double fa_h_incr_per_first_rd_port_       = 15 * g_ip->F_sz_um;
    double fa_h_incr_per_later_rd_port_       = 15 * g_ip->F_sz_um;
    double fa_w_incr_per_first_rw_or_wr_port_ = 20 * g_ip->F_sz_um;
    double fa_w_incr_per_later_rw_or_wr_port_ = 12 * g_ip->F_sz_um;
    double fa_w_incr_per_first_rd_port_       = 15 * g_ip->F_sz_um;
    double fa_w_incr_per_later_rd_port_       = 12 * g_ip->F_sz_um;
    double w_contact_                         = 2 * g_ip->F_sz_um;
    double overhead_w;
    double overhead_h;

    int h_tag_bits       = (dp.tagbits + 1)/2;
    uint32_t  RWP;
    uint32_t  ERP;
    uint32_t  EWP;
    if (dp.use_inp_params == 1)
    {
      RWP = dp.num_rw_ports;
      ERP = dp.num_rd_ports;
      EWP = dp.num_wr_ports;
    }
    else
    {
      RWP = g_ip->num_rw_ports;
      ERP = g_ip->num_rd_ports;
      EWP = g_ip->num_wr_ports;
    }

    if (RWP == 1 && ERP == 0 && EWP == 0)
    {
      overhead_w = 0;
      overhead_h = 0;
    }
    else if (RWP == 1 && ERP == 1 && EWP == 0)
    {
      overhead_w = fa_w_incr_per_first_rd_port_;
      overhead_h = fa_h_incr_per_first_rd_port_;
    }
    else if (RWP == 1 && ERP == 0 && EWP == 1)
    {
      overhead_w = fa_w_incr_per_first_rw_or_wr_port_;
      overhead_h = fa_h_incr_per_first_rw_or_wr_port_;
    }
    else if (RWP + EWP >= 2)
    {
      overhead_w = fa_w_incr_per_first_rw_or_wr_port_ +
        (RWP + EWP - 2)*fa_w_incr_per_later_rw_or_wr_port_ +
        ERP*fa_w_incr_per_later_rd_port_;
      overhead_h = fa_h_incr_per_first_rw_or_wr_port_ +
        (RWP + EWP - 2)*fa_h_incr_per_later_rw_or_wr_port_ +
        ERP*fa_h_incr_per_later_rd_port_;
    }
    else if (RWP == 0 && EWP == 0)
    {
      overhead_w = fa_w_incr_per_first_rd_port_ + (ERP - 1)*fa_w_incr_per_later_rd_port_;
      overhead_h = fa_h_incr_per_first_rd_port_ + (ERP - 1)*fa_h_incr_per_later_rd_port_;
    }
    else if (RWP == 0 && EWP == 1)
    {
      overhead_w = ERP * fa_w_incr_per_later_rd_port_;
      overhead_h = ERP * fa_h_incr_per_later_rd_port_;
    }
    else if (RWP == 1 && EWP == 0)
    {
      overhead_w = ERP * fa_w_incr_per_later_rd_port_;
      overhead_h = ERP * fa_h_incr_per_later_rd_port_;
    }
    else
    {
      cout << "unsupported combination of RWP, ERP, and EWP" << endl;
      exit(1);
    }

    area.h = (CAM2x2_h_1p + 2*overhead_h) * ((num_rows + 1)/2);
    area.w = 2*(h_tag_bits * ((CAM2x2_w_1p + 2*overhead_w) - w_contact_)) +
      floor(h_tag_bits / sram_num_cells_wl_stitching_)*g_tp.ram_wl_stitching_overhead_;
    // following line is commented out in the latest version of CACTI 5
    //+ (fa_row_NAND_w_ + fa_row_NOR_inv_w_)*(RWP + ERP + EWP);

    cell.h = (CAM2x2_h_1p + 2*overhead_h) / 2.0;
    cell.w = (CAM2x2_w_1p + 2*overhead_w - w_contact_) / 2.0;
*/
	  //should not add dummy row here since the dummy row do not need decoder
	  if (is_fa)// fully associative cache
	  {
		  num_cols_fa_cam  += g_ip->add_ecc_b_ ? (int)ceil(num_cols_fa_cam / num_bits_per_ecc_b_) : 0;
		  num_cols_fa_ram  += (g_ip->add_ecc_b_ ? (int)ceil(num_cols_fa_ram / num_bits_per_ecc_b_) : 0);
		  num_cols = num_cols_fa_cam + num_cols_fa_ram;
	  }
	  else
	  {
		  num_cols_fa_cam  += g_ip->add_ecc_b_ ? (int)ceil(num_cols_fa_cam / num_bits_per_ecc_b_) : 0;
		  num_cols_fa_ram  = 0;
		  num_cols = num_cols_fa_cam;
	  }

	  area.h = cam_cell.h * (num_rows + 1);//height of subarray is decided by CAM array. blank space in sram array are filled with dummy cells
	  area.w = cam_cell.w * num_cols_fa_cam + cell.w * num_cols_fa_ram
	  + ceil((num_cols_fa_cam + num_cols_fa_ram) / sram_num_cells_wl_stitching_)*g_tp.ram_wl_stitching_overhead_
	  + 16*g_tp.wire_local.pitch //the overhead for the NAND gate to connect the two halves
	  + 128*g_tp.wire_local.pitch;//the overhead for the drivers from matchline to wordline of RAM
  }

    assert(area.h>0);
    assert(area.w>0);
  compute_C();
}



Subarray::~Subarray()
{
}



double Subarray::get_total_cell_area()
{
//	cout << dp.is_tag << ", cell.h :" << cell.h << ", cell.w : " << cell.w << ", cell_area : " << cell.get_area() << endl;
//  return cell.get_area() * num_rows * num_cols;
    if (!(is_fa || dp.pure_cam))
	  return (cell.get_area() * num_rows * num_cols);
    else if (is_fa)
    { //for FA, this area includes the dummy cells in SRAM arrays.
      //return (cam_cell.get_area()*(num_rows+1)*(num_cols_fa_cam + num_cols_fa_ram));
      //cout<<"diff" <<cam_cell.get_area()*(num_rows+1)*(num_cols_fa_cam + num_cols_fa_ram)- cam_cell.h*(num_rows+1)*(cam_cell.w*num_cols_fa_cam + cell.w*num_cols_fa_ram)<<endl;
      return (cam_cell.h*(num_rows+1)*(cam_cell.w*num_cols_fa_cam + cell.w*num_cols_fa_ram));
    }
    else
      return (cam_cell.get_area()*(num_rows+1)*num_cols_fa_cam );

}



void Subarray::compute_C()
{
  double c_w_metal = cell.w * g_tp.wire_local.C_per_um;
  double r_w_metal = cell.w * g_tp.wire_local.R_per_um;
  double C_b_metal = cell.h * g_tp.wire_local.C_per_um;
  double C_b_row_drain_C;
  C_rwl = 0; // Alireza

  if (dp.is_dram)
  {
    C_wl = (gate_C_pass(g_tp.dram.cell_a_w, g_tp.dram.b_w, true, true) + c_w_metal) * num_cols;

    if (dp.ram_cell_tech_type == comm_dram)
    {
      C_bl = num_rows * C_b_metal;
    }
    else
    {
      C_b_row_drain_C = drain_C_(g_tp.dram.cell_a_w, NCH, 1, 0, cell.w, true, true) / 2.0;  // due to shared contact
      C_bl = num_rows * (C_b_row_drain_C + C_b_metal);
    }
  }
  else
  {
	  if (!(is_fa ||dp.pure_cam))
	 {
			C_rwl = (gate_C_pass(g_tp.sram.cell_rd_a_w, 0, false, true) + c_w_metal) * num_cols; // Alireza
			C_wl = (gate_C_pass(g_tp.sram.cell_a_w, (g_tp.sram.b_w-2*g_tp.sram.cell_a_w)/2.0, false, true)*2 + c_w_metal) * num_cols;
			C_b_row_drain_C = drain_C_(g_tp.sram.cell_a_w, NCH, 1, 0, cell.w, false, true) / 2.0;  // due to shared contact

			if(ceil(g_tp.sram.cell_rd_a_w/g_tp.min_w_nmos_) > 1)
				cout << "Subarray::compute_C():: gate_C_pass : g_tp.sram.cell_rd_a_w : "<< g_tp.sram.cell_rd_a_w << ", g_tp.min_w_nmos_ : "  << g_tp.min_w_nmos_ << endl;

			if(ceil(g_tp.sram.cell_a_w/g_tp.min_w_nmos_) > 1)
					cout << "Subarray::compute_C():: gate_C_pass : g_tp.sram.cell_a_w : "<< g_tp.sram.cell_a_w << ", g_tp.min_w_nmos_ : "  << g_tp.min_w_nmos_ << endl;

			if(ceil(g_tp.sram.cell_a_w/g_tp.min_w_nmos_) > 1)
					cout << "Subarray::compute_C():: drain_C_ : g_tp.sram.cell_a_w : "<< g_tp.sram.cell_a_w << ", g_tp.min_w_nmos_ : "  << g_tp.min_w_nmos_ << endl;


			C_bl = num_rows * (C_b_row_drain_C + C_b_metal);
	 }
	  else
	  {
			 //Following is wordline not matchline
			 //CAM portion
			 c_w_metal = cam_cell.w * g_tp.wire_local.C_per_um;
			 r_w_metal = cam_cell.w * g_tp.wire_local.R_per_um;
	         C_wl_cam = (gate_C_pass(g_tp.cam.cell_a_w, (g_tp.cam.b_w-2*g_tp.cam.cell_a_w)/2.0, false, true)*2 +
					  c_w_metal) * num_cols_fa_cam;
	         R_wl_cam = (r_w_metal) * num_cols_fa_cam;

	         if (!dp.pure_cam)
	         {
	        	 //RAM portion
	        	 c_w_metal = cell.w * g_tp.wire_local.C_per_um;
	        	 r_w_metal = cell.w * g_tp.wire_local.R_per_um;
	        	 C_wl_ram = (gate_C_pass(g_tp.sram.cell_a_w, (g_tp.sram.b_w-2*g_tp.sram.cell_a_w)/2.0, false, true)*2 +
	        			 c_w_metal) * num_cols_fa_ram;
	        	 R_wl_ram = (r_w_metal) * num_cols_fa_ram;
	         }
	         else
	         {
	        	 C_wl_ram = R_wl_ram =0;
	         }
	         C_wl = C_wl_cam + C_wl_ram;
	         C_wl += (16+128)*g_tp.wire_local.pitch*g_tp.wire_local.C_per_um;

	         R_wl = R_wl_cam + R_wl_ram;
	         R_wl += (16+128)*g_tp.wire_local.pitch*g_tp.wire_local.R_per_um;

	         //there are two ways to write to a FA,
	         //1) Write to CAM array then force a match on match line to active the corresponding wordline in RAM;
	         //2) using separate wordline for read/write and search in RAM.
	         //We are using the second approach.

	         //Bitline CAM portion This is bitline not searchline. We assume no sharing between bitline and searchline according to SUN's implementations.
	         C_b_metal = cam_cell.h * g_tp.wire_local.C_per_um;
	         C_b_row_drain_C = drain_C_(g_tp.cam.cell_a_w, NCH, 1, 0, cam_cell.w, false, true) / 2.0;  // due to shared contact
	         C_bl_cam = (num_rows+1) * (C_b_row_drain_C + C_b_metal);
	         //height of subarray is decided by CAM array. blank space in sram array are filled with dummy cells
	         C_b_row_drain_C = drain_C_(g_tp.sram.cell_a_w, NCH, 1, 0, cell.w, false, true) / 2.0;  // due to shared contact
	         C_bl = (num_rows +1) * (C_b_row_drain_C + C_b_metal);
	  }
  }
}

