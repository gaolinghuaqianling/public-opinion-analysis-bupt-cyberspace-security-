# -*- coding: utf-8 -*-
"""
报表导出 API 路由
提供舆情日报、舆情周报、事件专报的 Word / PDF 文档下载接口
"""
import os
import subprocess
import shutil
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.api.auth import get_current_user
from app.services.report_generator import (
    gather_daily_report_data,
    gather_weekly_report_data,
    gather_event_report_data,
    generate_report_docx,
)

router = APIRouter(prefix="/reports", tags=["报表导出"])

# PDF 相关常量
PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _check_soffice_available() -> bool:
    """检查系统是否安装了 LibreOffice（soffice 命令可用）"""
    return shutil.which("soffice") is not None


def _convert_docx_to_pdf(docx_path: str, output_dir: str) -> str:
    """
    使用 LibreOffice 将 Word 文档转换为 PDF
    返回 PDF 文件的绝对路径
    """
    result = subprocess.run(
        [
            "soffice", "--headless", "--convert-to", "pdf",
            "--outdir", output_dir, docx_path,
        ],
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice 转换失败：{result.stderr.decode('utf-8', errors='replace')}"
        )
    # 转换后的 PDF 与 docx 同名，仅后缀不同
    pdf_filename = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
    pdf_path = os.path.join(output_dir, pdf_filename)
    if not os.path.exists(pdf_path):
        raise RuntimeError("PDF 文件未生成，请检查 LibreOffice 是否正常运行")
    return pdf_path


def _build_file_response(filepath: str, media_type: str):
    """构建统一格式的 FileResponse"""
    filename = os.path.basename(filepath)
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type=media_type,
    )


# ==================== 日报接口 ====================
@router.get("/daily")
def generate_daily(
    format: str = Query(default="docx", description="导出格式：docx 或 pdf"),
    _user=Depends(get_current_user),
):
    """生成并下载舆情日报（支持 Word / PDF 格式）"""
    try:
        data = gather_daily_report_data()
        docx_path = generate_report_docx(data, "daily")

        # 如果请求 PDF 格式，先转为 PDF
        if format == "pdf":
            if not _check_soffice_available():
                return JSONResponse(
                    status_code=503,
                    content={"detail": "服务端未安装 LibreOffice，暂不支持 PDF 导出"},
                )
            output_dir = os.path.dirname(docx_path)
            pdf_path = _convert_docx_to_pdf(docx_path, output_dir)
            return _build_file_response(pdf_path, PDF_MEDIA_TYPE)

        return _build_file_response(docx_path, DOCX_MEDIA_TYPE)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成日报失败：{str(e)}")


# ==================== 周报接口 ====================
@router.get("/weekly")
def generate_weekly(
    format: str = Query(default="docx", description="导出格式：docx 或 pdf"),
    _user=Depends(get_current_user),
):
    """生成并下载舆情周报（支持 Word / PDF 格式）"""
    try:
        data = gather_weekly_report_data()
        docx_path = generate_report_docx(data, "weekly")

        if format == "pdf":
            if not _check_soffice_available():
                return JSONResponse(
                    status_code=503,
                    content={"detail": "服务端未安装 LibreOffice，暂不支持 PDF 导出"},
                )
            output_dir = os.path.dirname(docx_path)
            pdf_path = _convert_docx_to_pdf(docx_path, output_dir)
            return _build_file_response(pdf_path, PDF_MEDIA_TYPE)

        return _build_file_response(docx_path, DOCX_MEDIA_TYPE)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成周报失败：{str(e)}")


# ==================== 事件专报接口 ====================
@router.get("/event/{event_id}")
def generate_event_report(
    event_id: int,
    format: str = Query(default="docx", description="导出格式：docx 或 pdf"),
    _user=Depends(get_current_user),
):
    """生成并下载事件专报（支持 Word / PDF 格式）"""
    try:
        data = gather_event_report_data(event_id)
        if "error" in data:
            raise HTTPException(status_code=404, detail=data["error"])
        docx_path = generate_report_docx(data, "event")

        if format == "pdf":
            if not _check_soffice_available():
                return JSONResponse(
                    status_code=503,
                    content={"detail": "服务端未安装 LibreOffice，暂不支持 PDF 导出"},
                )
            output_dir = os.path.dirname(docx_path)
            pdf_path = _convert_docx_to_pdf(docx_path, output_dir)
            return _build_file_response(pdf_path, PDF_MEDIA_TYPE)

        return _build_file_response(docx_path, DOCX_MEDIA_TYPE)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成事件专报失败：{str(e)}")
