import kr.dogfoot.hwplib.object.HWPFile;
import kr.dogfoot.hwplib.object.bodytext.control.*;
import kr.dogfoot.hwplib.object.bodytext.control.ctrlheader.header.HeaderFooterApplyPage;
import kr.dogfoot.hwplib.object.bodytext.control.sectiondefine.NumberShape;
import kr.dogfoot.hwplib.object.bodytext.control.gso.ControlRectangle;
import kr.dogfoot.hwplib.object.bodytext.control.gso.GsoControl;
import kr.dogfoot.hwplib.object.bodytext.control.gso.GsoControlType;
import kr.dogfoot.hwplib.object.bodytext.control.table.Cell;
import kr.dogfoot.hwplib.object.bodytext.paragraph.Paragraph;
import kr.dogfoot.hwplib.tool.blankfilemaker.BlankFileMaker;
import kr.dogfoot.hwplib.writer.HWPWriter;

public class MakeHwpNestedFixture {
    private static Paragraph paragraph(String text) throws Exception {
        Paragraph result = BlankFileMaker.make().getBodyText().getSectionList().get(0)
            .getParagraph(0).clone();
        result.getControlList().clear();
        result.getText().getCharList().clear();
        result.getText().addString(text);
        return result;
    }

    private static Paragraph cell(Paragraph owner, String text) throws Exception {
        owner.getText().addExtendCharForTable();
        ControlTable table = (ControlTable) owner.addNewControl(ControlType.Table);
        table.getTable().setRowCount(1);
        table.getTable().setColumnCount(1);
        table.getTable().addCellCountOfRow(1);
        Cell cell = table.addNewRow().addNewCell();
        cell.getListHeader().setColSpan(1);
        cell.getListHeader().setRowSpan(1);
        cell.getListHeader().setParaCount(1);
        Paragraph child = paragraph(text);
        cell.getParagraphList().addParagraph(child);
        return child;
    }

    private static void stories(Paragraph owner) throws Exception {
        owner.getText().addExtendCharForHeader();
        ControlHeader header = (ControlHeader) owner.addNewControl(ControlType.Header);
        header.getHeader().setApplyPage(HeaderFooterApplyPage.BothPage);
        header.getParagraphList().addParagraph(paragraph("머리말 기준"));
        header.getListHeader().setParaCount(1);
        owner.getText().addExtendCharForFooter();
        ControlFooter footer = (ControlFooter) owner.addNewControl(ControlType.Footer);
        footer.getHeader().setApplyPage(HeaderFooterApplyPage.BothPage);
        footer.getParagraphList().addParagraph(paragraph("꼬리말 기준"));
        footer.getListHeader().setParaCount(1);
        var marker = owner.getText().addNewExtendControlChar();
        marker.setCode(17);
        byte[] addition = new byte[12];
        addition[3] = 'f'; addition[2] = 'n'; addition[1] = ' '; addition[0] = ' ';
        marker.setAddition(addition);
        ControlFootnote note = (ControlFootnote) owner.addNewControl(ControlType.Footnote);
        note.getHeader().setNumberShape(NumberShape.Number);
        note.getParagraphList().addParagraph(paragraph("각주 근거"));
        note.getListHeader().setParaCount(1);
        var endMarker = owner.getText().addNewExtendControlChar();
        endMarker.setCode(17);
        byte[] endAddition = new byte[12];
        endAddition[3] = 'e'; endAddition[2] = 'n'; endAddition[1] = ' '; endAddition[0] = ' ';
        endMarker.setAddition(endAddition);
        ControlEndnote endnote = (ControlEndnote) owner.addNewControl(ControlType.Endnote);
        endnote.getHeader().setNumberShape(NumberShape.Number);
        endnote.getParagraphList().addParagraph(paragraph("미지원 미주 내용"));
        endnote.getListHeader().setParaCount(1);
    }

    private static void caption(GsoControl picture, String text) throws Exception {
        picture.createCaption();
        picture.getCaption().getParagraphList().addParagraph(paragraph(text));
    }

    private static void figures(HWPFile document) throws Exception {
        var section = document.getBodyText().getSectionList().get(0);
        Paragraph root = section.getParagraph(0);
        root.getText().addString("그림 앞");
        root.getText().addExtendCharForGSO();
        caption(root.addNewGsoControl(GsoControlType.Picture), "그림 프론트엔드 대시보드");
        root.getText().addExtendCharForGSO();
        root.addNewGsoControl(GsoControlType.Picture);
        root.getText().addString("그림 뒤");
        Paragraph table = paragraph("표 문단");
        table.getText().addExtendCharForTable();
        ControlTable control = (ControlTable) table.addNewControl(ControlType.Table);
        control.getTable().setRowCount(1);
        control.getTable().setColumnCount(1);
        control.getTable().addCellCountOfRow(1);
        Cell cell = control.addNewRow().addNewCell();
        cell.getListHeader().setColSpan(1);
        cell.getListHeader().setRowSpan(1);
        cell.getListHeader().setParaCount(1);
        cell.getParagraphList().addParagraph(paragraph("표 셀 내용"));
        control.createCaption();
        control.getCaption().getParagraphList().addParagraph(paragraph("표 성능 지표"));
        section.insertParagraph(section.getParagraphCount(), table);
    }

    private static void textboxes(HWPFile document) throws Exception {
        Paragraph root = document.getBodyText().getSectionList().get(0).getParagraph(0);
        root.getText().addString("상자 앞");
        root.getText().addExtendCharForGSO();
        ControlRectangle box = (ControlRectangle) root.addNewGsoControl(GsoControlType.Rectangle);
        box.createTextBox();
        box.getTextBox().getParagraphList().addParagraph(paragraph("상자 안 첫 줄"));
        box.getTextBox().getParagraphList().addParagraph(paragraph("둘째 줄"));
        box.getTextBox().getListHeader().setParaCount(2);
        root.getText().addExtendCharForGSO();
        root.addNewGsoControl(GsoControlType.Picture);
        root.getText().addString("상자 뒤");
    }

    private static void marker(Paragraph owner, int code, String id) throws Exception {
        var character = owner.getText().addNewExtendControlChar();
        character.setCode(code);
        byte[] addition = new byte[12];
        for (int index = 0; index < 4; index++) addition[index] = (byte) id.charAt(3 - index);
        character.setAddition(addition);
    }

    private static void inert(HWPFile document) throws Exception {
        Paragraph root = document.getBodyText().getSectionList().get(0).getParagraph(0);
        root.getText().addString("링크 앞");
        root.getText().addExtendCharForHyperlinkStart();
        root.addNewControl(ControlType.FIELD_HYPERLINK);
        root.getText().addString("링크 글자");
        root.getText().addExtendCharForHyperlinkEnd();
        marker(root, 21, "pgnp");
        root.addNewControl(ControlType.PageNumberPosition);
        marker(root, 21, "nwno");
        root.addNewControl(ControlType.NewNumber);
        marker(root, 11, "eqed");
        root.addNewControl(ControlType.Equation);
        root.getText().addString("링크 뒤");
    }

    public static void main(String[] args) throws Exception {
        HWPFile document = BlankFileMaker.make();
        if (args.length > 1 && args[1].equals("inert")) {
            inert(document);
            HWPWriter.toFile(document, args[0]);
            return;
        }
        if (args.length > 1 && args[1].equals("textboxes")) {
            textboxes(document);
            HWPWriter.toFile(document, args[0]);
            return;
        }
        if (args.length > 1 && args[1].equals("figures")) {
            figures(document);
            HWPWriter.toFile(document, args[0]);
            return;
        }
        Paragraph root = document.getBodyText().getSectionList().get(0).getParagraph(0);
        root.getText().addString("본문 앞");
        root.getText().addNewNormalChar().setCode(0xd83d);
        root.getText().addNewNormalChar().setCode(0xde00);
        Paragraph outer = cell(root, "바깥 셀 앞");
        Paragraph inner = cell(outer, "중첩 셀 내용");
        outer.getText().addString("바깥 셀 뒤");
        root.getText().addString("본문 뒤");
        stories(root);
        if (args.length > 1 && args[1].equals("deep")) {
            for (int level = 0; level < 40; level++) inner = cell(inner, "깊이" + level);
        }
        if (args.length > 1 && !args[1].isEmpty() && !args[1].equals("deep")) {
            int count = args[1].equals("blocks") ? 10010 : args[1].equals("overflow") ? 1000 : 100;
            String text = args[1].equals("blocks") ? "단락" : "한글".repeat(1000);
            for (int index = 0; index < count; index++) {
                var section = document.getBodyText().getSectionList().get(0);
                section.insertParagraph(section.getParagraphCount(), paragraph(text));
            }
        }
        HWPWriter.toFile(document, args[0]);
    }
}
